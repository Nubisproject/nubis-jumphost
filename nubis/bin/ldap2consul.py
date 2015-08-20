#!/usr/bin/python

import os
import sys
import ConfigParser
import optparse
import ldap
import consul

_config = {}
DRYRUN = False

def load_config(config_file):
    global _config
    if not os.path.exists(config_file):
        print "ERROR: Config file '%s' not found." % config_file
        sys.exit(-1)
    config = ConfigParser.RawConfigParser()
    config.read(config_file)
    if 'ldap' not in config.sections():
        print "ERROR: [ldap] section not found in %s." % config_file
        sys.exit(-1)
    _config = config

def process_arguments():
    parser = optparse.OptionParser(version="%prog 0.1")
    parser.set_usage("%prog [options]\nRead users from LDAP and write them to Consul")
    parser.add_option('-d', '--dry-run', action='store_true', dest='dryrun',
        help="Show, but do not execute, any commands")
    parser.add_option('-f', dest='config', default='ldap2consul.conf',
        help="Config file. Default: %default")
    (options, args) = parser.parse_args()
    return options

def getLDAPUsers(ldap_conn):
    searchbase = _config.get('ldap', 'searchbase')
    searchfilter = _config.get('ldap', 'searchfilter')
    try:
        result_set = []
        sid = ldap_conn.search(searchbase, ldap.SCOPE_SUBTREE, searchfilter)
        result_type, result_data = ldap_conn.result(sid, 0)
        users = result_data[0][1]["member"]
    except ldap.LDAPError, e:
        print e
    return users

def getDataForUser(ldap_conn, user):
    searchbase = user
    searchfilter = user
    attributes = _config.get('ldap', 'attributes').split(" ")
    sid = ldap_conn.search(searchbase, ldap.SCOPE_BASE, attrlist=attributes)
    result_type, result_data = ldap_conn.result(sid, 0)
    return result_data[0][1]

def getAllUserdata():
    userdata = {}
    server = _config.get('ldap', 'server')
    binduser = _config.get('ldap', 'binduser')
    bindpass = _config.get('ldap', 'bindpass')
    ldap_conn = ldap.open(server)
    ldap_conn.simple_bind(binduser, bindpass)
    users = getLDAPUsers(ldap_conn)
    # userdata format: For a given user, their LDAP DN is the key
    # The value all of this key is a dictionary, containing all values specified by
    # 'attributes' in ldap2consul.conf
    # e.g.: print userdata['mail=dparsons@mozilla.com,o=com,dc=mozilla']['sshPublicKey']
    for user in users:
        data = getDataForUser(ldap_conn, user)
        userdata[user] = data
    return userdata

def writeToConsul(userdata):
    consul_host = _config.get('consul', 'server')
    consul_port = _config.get('consul', 'port')
    consul_scheme = _config.get('consul', 'scheme')
    consul_path = _config.get('consul', 'path')
    c = consul.Consul(host=consul_host, port=consul_port, scheme=consul_scheme)
    for user in userdata:
        for attr in userdata[user]:
            key = "%s/%s/%s" % (consul_path, user, attr)

            # This enables support for multiple ssh keys
            if attr == "sshPublicKey":
                keynum = 0
                for sshkey in userdata[user]["sshPublicKey"]:
                    consul_key = "%s/sshkey%s" % (key, keynum)
                    consul_value = userdata[user]["sshPublicKey"][keynum]
                    keynum += 1
                    if DRYRUN:
                        print "c.kv.put('%s', '%s')" % (consul_key, consul_value)
                        continue
                    else:
                        c.kv.put(consul_key, consul_value)
            else:
                # this is a non-sshkey attribute, so only considering the first
                # value per attr
                value = userdata[user][attr][0]
                if DRYRUN:
                    print "c.kv.put('%s', '%s')" % (key, value)
                    continue
                else:
                    c.kv.put(key, value)

def main():
    global DRYRUN
    options = process_arguments()
    if options.dryrun:
        DRYRUN = True
        print "Dry run mode enabled."
    load_config(options.config)
    userdata = getAllUserdata()
    writeToConsul(userdata)

if __name__ == '__main__':
    main()
