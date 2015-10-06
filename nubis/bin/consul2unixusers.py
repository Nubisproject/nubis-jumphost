#!/usr/bin/python

import os
import sys
import pwd
import ConfigParser
import optparse
import consul

USERADD="/usr/sbin/useradd"
DRYRUN=False

_config = {}

def load_config(config_file):
    global _config
    if not os.path.exists(config_file):
        print "ERROR: Config file %s not found." % config_file
        sys.exit(-1)
    config = ConfigParser.RawConfigParser()
    config.read(config_file)
    if 'consul' not in config.sections():
        print "ERROR: [consul] section not found in %s." % config_file
        sys.exit(-1)
    _config = config

def process_arguments():
    parser = optparse.OptionParser(version="%prog 0.1")
    parser.set_usage("%prog [options]\nRead users from Consul and create them")
    parser.add_option('-d', '--dry-run', action='store_true', dest='dryrun',
        help="Show, but do not execute, any commands")
    parser.add_option('-f', dest='config', default='consul2unixusers.conf',
        help="Config file. Default: %default")
    (options, args) = parser.parse_args()
    return options

def readUsersFromConsul():
    users = {}
    consul_host = _config.get('consul', 'server')
    consul_port = _config.get('consul', 'port')
    consul_scheme = _config.get('consul', 'scheme')
    consul_path = _config.get('consul', 'path')
    c = consul.Consul(host=consul_host, port=consul_port, scheme=consul_scheme)
    x = c.kv.get(consul_path, keys=True, separator='/')
    if x[1] == None:
        print "ERROR: No keys returned from Consul at %s://%s:%s/%s" % (
            consul_scheme, consul_host, consul_port, consul_path)
        sys.exit(-1)
    ldapCNs = x[1]
    for key in ldapCNs:
        uid = c.kv.get(key + 'uid')[1]["Value"]
        users[uid] = {}
        users[uid]["homeDirectory"] = c.kv.get(key + 'homeDirectory')[1]["Value"]
        users[uid]["loginShell"] = c.kv.get(key + 'loginShell')[1]["Value"]
        users[uid]["mail"] = c.kv.get(key + 'mail')[1]["Value"]
        users[uid]["uidNumber"] = c.kv.get(key + 'uidNumber')[1]["Value"]
        users[uid]["sshPublicKey"] = {}
        sshkeys = c.kv.get(key + 'sshPublicKey/', keys=True, separator='/')[1]
        for keypath in sshkeys:
            keynumber = keypath.split('/')[-1]
            users[uid]["sshPublicKey"][keynumber] = c.kv.get(keypath)
    return users

def user_exists(user):
    try:
        pwd.getpwnam(user)
    except KeyError:
        return False
    return True

def adduser(username, userdata):
    cmd = "%s -d '%s' -s '%s' -u '%s' -G sudo -m -U %s" % (
        USERADD, userdata["homeDirectory"], userdata["loginShell"],
        userdata["uidNumber"], username
    )
    if DRYRUN:
        print cmd
        return True
    else:
        return os.system(cmd)

def writeSSHKeysForUser(username, userdata):
    # Does their home directory exist? If not, abort, as it should have been
    # created by adduser()
    homedir = userdata["homeDirectory"]
    if not os.path.isdir(homedir):
        print "ssh key writeout aborted for Unix user '%s': homedir '%s' doesn't exist." % \
        (username, homedir)
        return False
    uid = pwd.getpwnam(username).pw_uid
    gid = pwd.getpwnam(username).pw_gid

    # Does their ~/.ssh directory exist? If not, create it"
    sshdir = homedir + "/.ssh"
    if not os.path.isdir(sshdir):
        if DRYRUN:
            print "os.mkdir('%s', '%s')" % (sshdir, 0700)
            print "os.chown('%s', '%s', '%s')" % (sshdir, uid, gid)
        else:
            os.mkdir(sshdir, 0700)
            os.chown(sshdir, uid, gid)

    # Do they already have a ~/.ssh/authorized_keys file? If not, create it
    authfilepath = sshdir + "/authorized_keys"
    if not os.path.isfile(authfilepath):
        if DRYRUN:
            print "os.mknod('%s', 0600)" % authfilepath
            print "os.chown('%s', '%s', '%s')" % (authfilepath, uid, gid)
        else:
            os.mknod(authfilepath, 0600)
            os.chown(authfilepath, uid, gid)

    # Iterate through the keys we have for this user. Does it already exist
    # in their authorized_keys? If not, add it.
    try:
        authfile_ro = open(authfilepath)
        authfilecontents = authfile_ro.read()
        authfile_ro.close()
    except:
        authfilecontents = ""
    for q in userdata["sshPublicKey"]:
        key = userdata["sshPublicKey"][q][1]["Value"]
        if key not in authfilecontents:
            # Key does not exist in the user's authorized_keys, so put it there
            if DRYRUN:
                print "authfile_rw = open('%s', 'a')" % authfilepath
                print "authfile_rw.write('%s' + '\n')" % key
                print 'authfile_rw.close()'
            else:
                authfile_rw = open(authfilepath, "a")
                authfile_rw.write(key + "\n")
                authfile_rw.close()

def main():
    global DRYRUN
    options = process_arguments()
    if options.dryrun:
        DRYRUN = True
        print "Dry run mode enabled."
    load_config(options.config)
    userdata = readUsersFromConsul()

    for user in userdata:
        if not user_exists(user):
            adduser(user, userdata[user])
        else:
            pass
            #print "adduser aborted for Unix user '%s': already exists." % user

        if user_exists(user):
            writeSSHKeysForUser(user, userdata[user])
        else:
            print "ssh key writeout aborted for Unix user '%s': user doesn't exist." % user

if __name__ == '__main__':
    main()
