#!/usr/bin/env python
"""Manage, delete, order Compute instances"""

from os import linesep
from SoftLayer.CCI import CCIManager
from SoftLayer.CLI import (
    CLIRunnable, Table, no_going_back, confirm, add_really_argument,
    mb_to_gb, listing, FormattedItem)
from SoftLayer.CLI.helpers import CLIAbort
from argparse import FileType


class ListCCIs(CLIRunnable):
    """ List all CCI's on the account"""
    action = 'list'

    @staticmethod
    def add_additional_args(parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '--hourly',
            help='List only hourly CCI\'s',
            action='store_true', default=False)
        group.add_argument(
            '--monthly',
            help='List only monthly CCI\'s',
            action='store_true', default=False)

        parser.add_argument(
            '--sortby',
            help="Sort table",
            choices=['id', 'datacenter', 'host', 'cores', 'memory',
                     'primary_ip', 'backend_ip'],
            default='host')

        parser.add_argument(
            '--tags',
            help="Filter by tag",
            nargs="+",
            required=False,
        )

    @staticmethod
    def execute(client, args):
        cci = CCIManager(client)

        results = cci.list_instances(hourly=args.hourly, monthly=args.monthly)

        t = Table([
            'id', 'datacenter', 'host',
            'cores', 'memory', 'primary_ip',
            'backend_ip', 'provisioning',
        ])
        t.sortby = args.sortby

        if args.tags:
            guests = []
            for g in results:
                tags = [x['tag']['name'] for x in g['tagReferences']]
                if any(_tag in args.tags for _tag in tags):
                    guests.append(g)
        else:
            guests = results

        for guest in guests:
            t.add_row([
                guest['id'],
                guest.get('datacenter', {}).get('name', 'unknown'),
                guest['fullyQualifiedDomainName'],
                guest['maxCpu'],
                mb_to_gb(guest['maxMemory']),
                guest.get('primaryIpAddress', '???'),
                guest.get('primaryBackendIpAddress', '???'),
                guest.get('activeTransaction', {}).get(
                    'transactionStatus', {}).get('friendlyName', ''),
            ])

        return t


class CCIDetails(CLIRunnable):

    action = 'detail'

    @staticmethod
    def add_additional_args(parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '--id',
            help='id of CCI')

        group.add_argument(
            '--name',
            help='Fully qualified domain name')

        group.add_argument(
            '--public-ip',
            help='public ip of CCI',
            dest='public_ip'
        )

        parser.add_argument(
            "--passwords",
            help='Show passwords (check over your shoulder!)',
            action='store_true', default=False)

        parser.add_argument(
            '--price',
            help='Show associated prices',
            action='store_true', default=False)

    @staticmethod
    def execute(client, args):
        cci = CCIManager(client)

        t = Table(['Name', 'Value'])
        t.align['Name'] = 'r'
        t.align['Value'] = 'l'

        output = [
            ("id", "{0[id]}",),
            ("hostname", "{0[fullyQualifiedDomainName]}",),
            ("status", "{0[status][name]}",),
            ("state", "{0[powerState][name]}",),
            ("datacenter", "{0[datacenter][name]}",),
            ("cores", "{0[maxCpu]}",),
            ("memory", "{0[maxMemory]}",),
            ("public_ip", "{0[primaryIpAddress]}",),
            ("private_ip", "{0[primaryBackendIpAddress]}",),
            ("os", "{0[operatingSystem][softwareLicense]"
                "[softwareDescription][name]} "),
        ]

        result = cci.get_instance(args.id)

        for o in output:
            if o[0] == 'memory':
                t.add_row([o[0], mb_to_gb(o[1].format(result))])
            else:
                t.add_row([o[0], o[1].format(result)])

        if args.price:
            t.add_row(['price rate', result['billingItem']['recurringFee']])

        if args.passwords:
            user_strs = []
            for item in result['operatingSystem']['passwords']:
                user_strs.append(
                    "%s %s" % (item['username'], item['password']))
            t.add_row(['users', listing(user_strs)])

        tag_row = []
        for tag in result['tagReferences']:
            tag_row.append(tag['tag']['name'])

        if tag_row:
            t.add_row(['tags', listing(tag_row, separator=',')])

        ptr_domains = client['Virtual_Guest'].\
            getReverseDomainRecords(id=args.id)[0]

        for ptr in ptr_domains['resourceRecords']:
            t.add_row(['ptr', ptr['data']])

        return t


class CreateOptionsCCI(CLIRunnable):
    """ Output available available options when creating a CCI """

    action = 'options'

    @staticmethod
    def add_additional_args(parser):
        filters = ['all', 'datacenter', 'cpu', 'nic', 'disk', 'os', 'memory']
        for f in filters:
            parser.add_argument(
                '--%s' % f,
                help="show %s options" % f,
                dest='filters',
                default=[],
                action='append_const',
                const=f)

    @staticmethod
    def execute(client, args):
        cci = CCIManager(client)
        result = cci.get_create_options()
        show_all = False
        if len(args.filters) == 0 or 'all' in args.filters:
            show_all = True

        t = Table(['Name', 'Value'])
        t.align['Name'] = 'r'
        t.align['Value'] = 'l'

        if 'datacenter' in args.filters or show_all:
            datacenters = [dc['template']['datacenter']['name']
                           for dc in result['datacenters']]
            t.add_row(['datacenter', listing(datacenters, separator=',')])

        if 'cpu' in args.filters or show_all:
            standard_cpu = filter(
                lambda x: not x['template'].get(
                    'dedicatedAccountHostOnlyFlag', False),
                result['processors'])

            ded_cpu = filter(
                lambda x: x['template'].get(
                    'dedicatedAccountHostOnlyFlag', False),
                result['processors'])

            def cpus_row(c, name):
                cpus = []
                for x in c:
                    cpus.append(str(x['template']['startCpus']))

                t.add_row(['cpus (%s)' % name, listing(cpus, separator=',')])

            cpus_row(ded_cpu, 'private')
            cpus_row(standard_cpu, 'standard')

        if 'memory' in args.filters or show_all:
            memory = [
                str(m['template']['maxMemory']) for m in result['memory']]
            t.add_row(['memory', listing(memory, separator=',')])

        if 'os' in args.filters or show_all:
            os = [
                o['template']['operatingSystemReferenceCode'] for o in
                result['operatingSystems']]

            os = sorted(os)
            os_summary = set()

            for o in os:
                os_summary.add(o[0:o.find('_')])

            for s in sorted(os_summary):
                t.add_row(['os (%s)' % linesep.join(
                    sorted(filter(lambda x: x[0:len(s)] == s, os))
                )])

        if 'disk' in args.filters or show_all:
            local_disks = filter(
                lambda x: x['template'].get('localDiskFlag', False),
                result['blockDevices'])

            san_disks = filter(
                lambda x: not x['template'].get('localDiskFlag', False),
                result['blockDevices'])

            def block_rows(blocks, name):
                simple = {}
                for block in blocks:
                    b = block['template']['blockDevices'][0]
                    bid = b['device']
                    size = b['diskImage']['capacity']

                    if bid not in simple:
                        simple[bid] = []

                    simple[bid].append(str(size))

                for b in sorted(simple.keys()):
                    t.add_row([
                        '%s disk(%s)' % (name, b),
                        listing(simple[b], separator=',')]
                    )

            block_rows(local_disks, 'local')
            block_rows(san_disks, 'san')

        if 'nic' in args.filters or show_all:
            speeds = []
            for x in result['networkComponents']:
                speed = x['template']['networkComponents'][0]['maxSpeed']
                speeds.append(str(speed))

            speeds = sorted(speeds)

            t.add_row(['nic', listing(speeds, separator=',')])

        return t


class CreateCCI(CLIRunnable):
    """ Order and create a CCI
    (see `sl cci options` for choices)"""

    action = 'create'

    @staticmethod
    def add_additional_args(parser):
        # Required options
        parser.add_argument(
            '--hostname', '-H',
            help='Host portion of the FQDN',
            type=str,
            required=True,
            metavar='server1')

        parser.add_argument(
            '--domain', '-D',
            help='Domain portion of the FQDN',
            type=str,
            required=True,
            metavar='example.com')

        parser.add_argument(
            '--cpu', '-c',
            help='Number of CPU cores',
            type=int,
            required=True,
            metavar='#')

        parser.add_argument(
            '--memory', '-m',
            help='Memory in mebibytes (n * 1024)',
            type=str,
            required=True)

        install = parser.add_mutually_exclusive_group(required=True)
        install.add_argument(
            '--os', '-o',
            help='OS install code. Tip: you can also specify <OS>_LATEST',
            type=str)
        install.add_argument(
            '--image',
            help='Image GUID',
            type=str,
            metavar='GUID')

        billable = parser.add_mutually_exclusive_group(required=True)
        billable.add_argument(
            '--hourly',
            help='Hourly rate instance type',
            action='store_true')
        billable.add_argument(
            '--monthly',
            help='Monthly rate instance type',
            action='store_true')

        # Optional arguments
        parser.add_argument(
            '--datacenter', '--dc', '-d',
            help='datacenter shortname (sng01, dal05, ...). '
            'Note: Omitting this value defaults to the first '
            'available datacenter',
            type=str,
            default='')

        parser.add_argument(
            '--private',
            help='Allocate a private CCI',
            action='store_true',
            default=False)

        g = parser.add_mutually_exclusive_group()
        g.add_argument(
            '--userdata', '-u',
            help="user defined metadata string",
            type=str,
            default=None)
        g.add_argument(
            '--userfile', '-F',
            help="read userdata from file",
            type=FileType('r'))

        parser.add_argument(
            '--test', '--dryrun', '--dry-run',
            help='Do not create CCI, just get a quote',
            action='store_true',
            default=False)
        add_really_argument(parser)

    @staticmethod
    def execute(client, args):
        cci = CCIManager(client)

        data = {
            "hourly": args.hourly,
            "cpus": args.cpu,
            "domain": args.domain,
            "hostname": args.hostname,
            "private": args.private,
            "local_disk": True,
        }

        try:
            memory = int(args.memory)
            if memory < 1024:
                memory = memory * 1024
        except ValueError:
            unit = args.memory[-1]
            memory = int(args.memory[0:-1])
            if unit in ['G', 'g']:
                memory = memory * 1024
            if unit in ['T', 'r']:
                memory = memory * 1024 * 1024

        data["memory"] = memory

        if args.monthly:
            data["hourly"] = False

        if args.os:
            data["os_code"] = args.os

        if args.image:
            data["image_id"] = args.image

        if args.datacenter:
            data["datacenter"] = args.datacenter

        if args.userdata:
            data['userdata'] = args.userdata
        elif args.userfile:
            data['userdata'] = args.userfile.read()

        if args.test:
            result = cci.verify_create_instance(**data)
            output = FormattedItem("Test: Success!")
        elif args.really or confirm(
                prompt_str="This action will incur charges on "
                "your account. Continue?", allow_empty=True):
            result = cci.create_instance(**data)
            output = FormattedItem('Order placed successfully')
        else:
            raise CLIAbort('Aborting CCI order.')

        return result, output


class CancelCCI(CLIRunnable):
    """ Cancel a running CCI """

    action = 'cancel'

    @staticmethod
    def add_additional_args(parser):
        parser.add_argument('id', help='The ID of the CCI to cancel')
        add_really_argument(parser)

    @staticmethod
    def execute(client, args):
        cci = CCIManager(client)
        if args.really or no_going_back(args.id):
            cci.cancel_instance(args.id)
        else:
            CLIAbort('Aborted')


class ManageCCI(CLIRunnable):
    """ Manage active CCI"""

    action = 'manage'

    @staticmethod
    def add_additional_args(parser):
        manage = parser.add_subparsers(dest='manage')

        def add_subparser(parser, arg, help, func):
            sp = parser.add_parser(arg, help=help)
            sp.add_argument(
                'instance',
                help='Instance ID')
            sp.set_defaults(func=func)

            return sp

        po = add_subparser(
            manage, 'poweroff',
            'Power off instance',
            ManageCCI.exec_shutdown)
        g = po.add_mutually_exclusive_group()
        g.add_argument(
            '--soft',
            help='Request the instance to shutdown gracefully',
            action='store_true')

        po = add_subparser(
            manage, 'reboot',
            'Reboot the instance',
            ManageCCI.exec_reboot)
        g = po.add_mutually_exclusive_group()
        g.add_argument(
            '--cycle', '--hard',
            help='Power cycle the instance (off, then on)',
            action='store_true')
        g.add_argument(
            '--soft',
            help='Attempts to safely reboot the instance',
            action='store_true')

        add_subparser(
            manage, 'poweron',
            'Power on instance',
            ManageCCI.exec_poweron)

        add_subparser(
            manage, 'pause',
            'Pause a running instance',
            ManageCCI.exec_pause)

        add_subparser(
            manage, 'resume',
            'Unpause a paused instance',
            ManageCCI.exec_resume)

    @staticmethod
    def execute(client, args):
        return args.func(client, args)

    @staticmethod
    def exec_shutdown(client, args):
        vg = client['Virtual_Guest']
        if args.soft:
            result = vg.powerOffSoft(id=args.instance)
        elif args.cycle:
            result = vg.powerCycle(id=args.instance)
        else:
            result = vg.powerOff(id=args.instance)

        return FormattedItem(result)

    @staticmethod
    def exec_poweron(client, args):
        vg = client['Virtual_Guest']
        return vg.powerOn(id=args.instance)

    @staticmethod
    def exec_pause(client, args):
        vg = client['Virtual_Guest']
        return vg.pause(id=args.instance)

    @staticmethod
    def exec_resume(client, args):
        vg = client['Virtual_Guest']
        return vg.resume(id=args.instance)

    @staticmethod
    def exec_reboot(client, args):
        vg = client['Virtual_Guest']
        if args.cycle:
            result = vg.rebootHard(id=args.instance)
        elif args.soft:
            result = vg.rebootSoft(id=args.instance)
        else:
            result = vg.rebootDefault(id=args.instance)

        return result


class NetworkCCI(CLIRunnable):
    """ manage network settings """

    action = 'network'

    @staticmethod
    def add_additional_args(parser):

        def add_subparser(parser, arg, help, func):
            sp = parser.add_parser(arg, help=help)
            sp.add_argument(
                'instance',
                help='Instance ID')
            g = sp.add_mutually_exclusive_group(required=True)
            g.add_argument(
                '--public',
                help='Disable public port',
                action='store_true')
            g.add_argument(
                '--private',
                help='Disable private port',
                action='store_true')

            sp.set_defaults(func=func)
            return sp

        manage = parser.add_subparsers(dest='network')

        add_subparser(
            manage, 'details',
            'Get network information',
            NetworkCCI.exec_detail)

        po = add_subparser(
            manage, 'port',
            'Set port speed or disable port',
            NetworkCCI.exec_port)

        po.add_argument(
            '--speed',
            type=int,
            choices=[0, 10, 100, 1000, 10000],
            help='Set port speed. 0 disables port',
            required=True)

    @staticmethod
    def execute(client, args):
        return args.func(client, args)

    @staticmethod
    def exec_port(client, args):
        vg = client['Virtual_Guest']
        if args.public:
            func = vg.setPublicNetworkInterfaceSpeed
        elif args.private:
            func = vg.setPrivateNetworkInterfaceSpeed

        result = func(args.speed, id=args.instance)
        if result:
            return "Success"
        else:
            return result

    @staticmethod
    def exec_detail(client, args):
        print "TODO"  # TODO this should print out default gateway and stuff


class CCIDNS(CLIRunnable):
    """ DNS related actions to a CCI"""

    action = 'dns'

    @staticmethod
    def add_additional_args(parser):
        manage = parser.add_subparsers(dest='dns')

        def add_subparser(parser, arg, help, func):
            sp = parser.add_parser(arg, help=help, description=help)
            sp.add_argument(
                'instance',
                help='Instance ID')
            sp.set_defaults(func=func)

            return sp

        po = add_subparser(
            manage, 'sync',
            'Sync hostname to A and PTR records',
            CCIDNS.exec_sync)
        po.add_argument(
            '--a', '--A',
            help='Sync only the A record',
            default=[],
            action='append_const',
            const='a',
            dest='sync')
        po.add_argument(
            '--ptr', '--PTR',
            help='Sync only the PTR record',
            default=[],
            action='append_const',
            const='ptr',
            dest='sync')

        add_really_argument(po)

    @staticmethod
    def execute(client, args):
        return args.func(client, args)

    @staticmethod
    def exec_sync(client, args):
        from SoftLayer.DNS import DNSManager, DNSZoneNotFound
        dns = DNSManager(client)
        cci = CCIManager(client)

        def sync_a_record():
            #hostname = instance['fullyQualifiedDomainName']
            records = dns.search_record(
                instance['domain'],
                instance['hostname'],
            )

            if not records:
                # don't have a record, lets add one to the base zone
                dns.create_record(
                    zone['id'],
                    instance['hostname'],
                    'a',
                    instance['primaryIpAddress'],
                    ttl=7200)
            else:
                recs = filter(lambda x: x['type'].lower() == 'a', records)
                if len(recs) != 1:
                    raise CLIAbort("Aborting A record sync, found %d "
                            "A record exists!" % len(recs))
                rec = recs[0]
                rec['data'] = instance['primaryIpAddress']
                dns.edit_record(rec)

        def sync_ptr_record():
            host_rec = instance['primaryIpAddress'].split('.')[-1]
            ptr_domains = client['Virtual_Guest'].\
                getReverseDomainRecords(id=instance['id'])[0]
            edit_ptr = None
            for ptr in ptr_domains['resourceRecords']:
                if ptr['host'] == host_rec:
                    edit_ptr = ptr
                    break

            if edit_ptr:
                edit_ptr['data'] = instance['fullyQualifiedDomainName']
                dns.edit_record(edit_ptr)
            else:
                dns.create_record(
                    ptr_domains['id'],
                    host_rec,
                    'ptr',
                    instance['fullyQualifiedDomainName'],
                    ttl=7200)

        instance = cci.get_instance(args.instance)

        if not instance['primaryIpAddress']:
            raise CLIAbort('No primary IP address associated with this CCI')

        try:
            zone = dns.get_zone(instance['domain'])
        except DNSZoneNotFound:
            raise CLIAbort("Unable to create A record, "
                "no zone found matching: %s" % instance['domain'])

        go_for_it = args.really or confirm(
            "Attempt to update DNS records for %s"
                % instance['fullyQualifiedDomainName'])

        if not go_for_it:
            raise CLIAbort("Aborting DNS sync")

        both = len(args.sync) == 0

        if both or 'a' in args.sync:
            sync_a_record()

        if both or 'ptr' in args.sync:
            sync_ptr_record()