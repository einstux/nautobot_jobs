from nautobot.apps import jobs
from nautobot.ipam.models import IPAddressToInterface
from fqdn import FQDN

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


jobs.register_jobs(SetDNSEntryOnIP)
