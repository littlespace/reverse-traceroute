#!/usr/bin/env python2

from config import *
from ip import IP
from mtr import Mtr
from paris_traceroute import ParisTraceroute
from path_comparator import PathComparator
from probe_selector import ProbeSelector
from Renderers.mtr import MtrRenderer
from Renderers.paris_traceroute import ParisTracerouteRenderer
from Renderers.traceroute import TracerouteRenderer
from ripe.atlas.cousteau import (
  Traceroute,
  AtlasSource,
  AtlasCreateRequest,
  AtlasResultsRequest
)
from time import sleep
from whois import Whois
import click
import logging
import sys

logging.getLogger().setLevel(logging.INFO)


class RIPEException(Exception):
    pass


class ReverseTraceroute(object):

    def __init__(self, distant_host, local_host, probe_count, protocol, description, verbose):
        self.distant_host = distant_host
        self.local_host = local_host if local_host is not None else IP().ip
        self.protocol = protocol
        self.description = description
        self.verbose = verbose
        self.probe_count = probe_count
        whois = Whois(distant_host)  # TODO: this can f*ck up, do somewhere else
        ps = ProbeSelector(
            asn=whois.get_asn(),
            country_code=whois.get_country(),
            target=distant_host,
            probe_count=probe_count
        )
        self.probe_ids = [str(x['prb_id']) for x in ps.get_near_probes_results()]

    def create_measurement(self):
        traceroute = Traceroute(
            af=4,
            target=self.local_host,
            protocol=self.protocol.upper(),
            description=self.description,
            paris=16,
            timeout=4000,
            packets=4
        )

        source = AtlasSource(
            type="probes",
            value=",".join(self.probe_ids),
            requested=len(self.probe_ids)
        )

        atlas_request = AtlasCreateRequest(
            key=ATLAS_API_KEY,
            measurements=[traceroute],
            sources=[source],
            is_oneoff=True
        )
        return atlas_request.create()

    def wait_for_all_results(self, msm_id, probe_count, limit=900):  # 15m timeout
        attempts = 0
        res = []
        while attempts < limit:
            res = self.get_result(msm_id)
            attempts += 1
            if len(res) == probe_count:
                break
            sleep(1)
        return res

    def get_result(self, msm_id):
        kwargs = {
            "msm_id": msm_id,
        }
        is_success, results = AtlasResultsRequest(**kwargs).create()
        return results

    def run(self):
        if self.verbose:
            logging.info('Gathering ripe probes.')

        is_success, response = self.create_measurement()

        if not is_success:
            raise RIPEException(response)

        if self.verbose:
            logging.info('Waiting for results.')
        msm = response["measurements"][0]
        results = self.wait_for_all_results(msm_id=msm, probe_count=self.probe_count)
        return results


@click.command()
@click.option(
    "--local-host", help="Host the RIPE traceroute is targeted to, defaults to this machine's address", required=False
)
@click.option(
    "--protocol", help="Protocol to use - ICMP, UDP, TCP, defaults to ICMP", required=False, default='ICMP'
)
@click.option(
    "--distant-hosts-file", help="Run traceroute from all hosts in given file towards local-host", required=False,
)
@click.option(
    "--probe-count", help="Number of RIPE probes to request", required=False, default=1
)
@click.option(
    "--description", help="Measurement description", required=False, default="Reverse traceroute measurement"
)
@click.option(
    "-v", "--verbose", help="verbose output", count=True
)
@click.argument("distant-host")
def run(distant_host, local_host, protocol, distant_hosts_file, probe_count, description, verbose):
    if distant_hosts_file is not None:
        try:
            with open(distant_hosts_file, 'r') as ipfile:
                iplist = [x.rstrip() for x in ipfile.readlines()]
                for host in iplist:
                    # mtr = Mtr(distant_host=host)
                    # forward_path = mtr.create_measurement()
                    # rt = ReverseTraceroute(
                    #     distant_host=distant_host,
                    #     local_host=local_host,
                    #     probe_count=probe_count,
                    #     protocol=protocol,
                    #     description=description,
                    #     verbose=verbose
                    # )
                    # results = rt.run()
                    #
                    # tr = TracerouteRenderer()
                    # reverse_path = tr.render(results)
                    pass
        except IOError as error:
            logging.error(error.message)
            sys.exit(1)
    elif distant_host is not None:
        if verbose:
            logging.info(
                'running Paris-traceroute towards {}.'.format(distant_host)
            )
        forward_traceroute = ParisTraceroute(distant_host, protocol=protocol)
        forward_traceroute.start()

        # rt = ReverseTraceroute(
        #     distant_host=distant_host,
        #     local_host=local_host,
        #     probe_count=probe_count,
        #     protocol=protocol,
        #     description=description,
        #     verbose=verbose
        # )
        # results = rt.run()

        forward_traceroute.join()

        if forward_traceroute.errors:
            if verbose:
                logging.info(
                    'Don\'t have root proviledges for paris-traceroute, '
                    'using mtr instead.'
                )
            print "Forward path:"
            forward_traceroute = Mtr(distant_host)
            forward_traceroute.start()
            forward_traceroute.join()
            parsed_ft_results = MtrRenderer.parse(forward_traceroute.output)
            MtrRenderer.render(parsed_ft_results)
        else:
            print "Forward path:"
            parsed_ft_results = ParisTracerouteRenderer.parse(forward_traceroute.output)
            ParisTracerouteRenderer.render(parsed_ft_results)

        kwargs = {
            "msm_id": 12237628
        }

        is_success, results = AtlasResultsRequest(**kwargs).create()

        print "Return path:"
        parsed_rt_results = TracerouteRenderer.parse(results)
        return_path = TracerouteRenderer.render(parsed_rt_results)
        print return_path

        path_comparator = PathComparator(parsed_ft_results, parsed_rt_results)
        path_comparator.print_asn_paths()


        import IPython;IPython.embed()
        p_count = path_comparator.find_probes_count(parsed_ft_results)



        return
        symmetrical = path_comparator.compare_paths_asns()

        if symmetrical:
            print "ASN Paths appear to be symmetrical"
        else:
            print "ASN Paths appear to be asymmetrical"

    else:
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    run()