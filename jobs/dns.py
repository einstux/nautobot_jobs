import ipaddress
import json
from nautobot.apps import jobs
from nautobot.ipam.models import IPAddressToInterface, Prefix
from fqdn import FQDN
import desec.api

name = "DNS Tasks"


class SetDNSEntryOnIP(jobs.Job):
    class Meta:
        name = "Set DNS Entries on IP Addresses"
        has_sensitive_variables = False
        is_singleton = True

    def run(self):
        all_ip_with_interfaces = self.get_all_ips_with_interface()
        for ip_with_interface in all_ip_with_interfaces:
            self.process_ip(ip_with_interface)

    def process_ip(self, ip_with_interface):
        ip_object = ip_with_interface.ip_address
        device = ip_with_interface.interface.device
        hostname = device.name
        interface_name = ip_with_interface.interface.name

        self.logger.debug(
            f"Processing IP: {ip_object}, Host: {hostname}, Interface: {interface_name}",
            extra={"object": ip_object},
        )

        if ip_object.ip_version == 4 and device.primary_ip4_id == ip_object.id:
            self.validate_and_save_fqdn(ip_object, hostname)
            return

        if ip_object.ip_version == 6 and device.primary_ip6_id == ip_object.id:
            self.validate_and_save_fqdn(ip_object, hostname)
            return

        prettified_interface_name = self.convert_interface_name(interface_name)
        proposed_fqdn = f"{prettified_interface_name}.{hostname}"
        self.validate_and_save_fqdn(ip_object, proposed_fqdn)

    def convert_interface_name(self, interface_name):
        interface_name = interface_name.replace(".", "-")
        interface_name = interface_name.replace("/", "-")

        return interface_name

    def validate_and_save_fqdn(self, ip_object, proposed_fqdn):
        fqdn = FQDN(proposed_fqdn)
        if fqdn.is_valid:
            ip_object.dns_name = fqdn.absolute
            ip_object.save()
        else:
            self.logger.error(
                f"Tried to set FQDN to {proposed_fqdn}, but validation failed!",
                extra={"object": ip_object},
            )

    def get_all_ips_with_interface(self):
        self.logger.debug("Getting all IPs with interface")

        return IPAddressToInterface.objects.all()


class SyncReverseZones(jobs.Job):
    class Meta:
        name = "Syncs the entries from prefixes to the right reverse zone"
        has_sensitive_variables = False
        is_singleton = True

    def __init__(self):
        super().__init__()
        self.logger.debug("Reading the token")
        with open("/opt/nautobot/secrets/desec.json", "r") as datafile:
            desec_secret = json.load(datafile)
        self.desec_client = desec.api.APIClient(desec_secret["token"])

    def run(self):
        prefixes = self.get_prefixes_with_reverse_zone()
        for prefix in prefixes:
            self.get_all_entries_from_prefix_and_update_zone(prefix)

    def get_prefixes_with_reverse_zone(self):
        self.logger.debug("Getting prefixes with reverse zone")
        reverse_prefixes = []
        pa = Prefix.objects.all()
        for p in pa:
            if p.cf["reverse_zone"] is not None:
                reverse_prefixes.append(p)
        return reverse_prefixes

    def get_all_entries_from_prefix_and_update_zone(self, prefix):
        self.logger.debug(
            f"Processing Prefix: {prefix}",
            extra={"object": prefix},
        )

        reverse_zone_name = prefix.cf["reverse_zone"]
        rr_entries = []

        ips = prefix.all_ips.filter(dns_name__isnull=False)

        for ip in ips:
            if len(ip.dns_name) == 0:
                continue
            python_ip = ipaddress.ip_address(ip.host)
            reverse_entry = python_ip.reverse_pointer

            reverse_entry = reverse_entry.replace(f".{reverse_zone_name}", "")
            self.logger.debug(
                f"Processing IP: {ip}, Reverse Pointer is: {reverse_entry}",
                extra={"object": ip},
            )

            entry = {
                "subname": reverse_entry,
                "type": "PTR",
                "ttl": 3600,
                "records": [ip.dns_name],
            }
            rr_entries.append(entry)

        rr_entries.append(
            {
                "subname": "",
                "type": "NS",
                "ttl": 3600,
                "records": ["ns1.desec.io.", "ns2.desec.org."],
            }
        )

        self.logger.debug(rr_entries, extra={"object": prefix})

        self.desec_client.update_bulk_record(
            domain=reverse_zone_name, rrset_list=rr_entries, exclusive=True
        )


jobs.register_jobs(SetDNSEntryOnIP)
jobs.register_jobs(SyncReverseZones)
