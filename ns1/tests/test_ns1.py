import json

import pytest

from datadog_checks.base import ConfigurationError
from datadog_checks.ns1 import Ns1Check


def test_empty_instance(aggregator, instance_empty):
    with pytest.raises(ConfigurationError):
        _ = Ns1Check('ns1', {}, [instance_empty])


def test_config(aggregator, instance):
    check = Ns1Check('ns1', {}, [instance])
    assert check.api_endpoint is not None
    aggregator.assert_all_metrics_covered()


def test_no_key(aggregator, instance_nokey):
    with pytest.raises(ConfigurationError):
        _ = Ns1Check('ns1', {}, [instance_nokey])


def test_no_metrics(aggregator, instance_nometrics):

    with pytest.raises(ConfigurationError):
        _ = Ns1Check('ns1', {}, [instance_nometrics])


def test_parse_metrics(aggregator, instance):
    check = Ns1Check('ns1', {}, [instance])
    metric = instance["metrics"]

    assert len(metric) > 0
    assert check.api_endpoint is not None


def test_url_gen_ddi(aggregator, instance_ddi, requests_mock):
    check = Ns1Check('ns1', {}, [instance_ddi])
    aggregator.assert_all_metrics_covered()
    url = "{apiendpoint}/v1/dhcp/scopegroup".format(apiendpoint=check.api_endpoint)
    ddiresponse = '''
    [
        {
            "dhcp_service_id": 3,
            "name": "scope1",
            "client_class_ids": [],
            "dhcpv4": {
                "enabled": true,
                "options": [
                    {
                        "name": "dhcpv4/example-single-type",
                        "value": "markmpeterson.xyz"
                    }
                ],
                "rebind_timer_secs": 43200,
                "renew_timer_secs": 21600,
                "valid_lifetime_secs": 86400,
                "echo_client_id": true,
                "match_client_id": true,
                "synthesize_dns_records": {
                    "enabled": true
                }
            },
            "dhcpv6": {
                "enabled": false,
                "options": [],
                "synthesize_dns_records": {}
            },
            "blocked_tags": [],
            "local_tags": [
                "Site Code",
                "auth:Security Lvl"
            ],
            "tags": {
                "Site Code": "DO",
                "auth:Security Lvl": "2"
            },
            "id": 2,
            "network_id": 1,
            "template_config": []
        }
    ]
    '''
    requests_mock.get(url, text=ddiresponse)
    checkUrl = check.create_url(check.metrics, check.query_params)

    assert len(checkUrl) > 0
    assert check.api_endpoint is not None
    # leases
    assert checkUrl["leases"][0] == "https://localhost/v1/stats/leases?period=24h"
    assert checkUrl["leases.2"][0] == "https://localhost/v1/stats/leases/2?period=24h"
    # lps
    assert checkUrl["peak_lps"][0] == "https://localhost/v1/stats/lps?period=24h"
    assert checkUrl["peak_lps.2"][0] == "https://localhost/v1/stats/lps/2?period=24h"


def test_url_gen(aggregator, instance_1, requests_mock):
    check = Ns1Check('ns1', {}, [instance_1])
    aggregator.assert_all_metrics_covered()

    url = "{apiendpoint}/v1/pulsar/apps".format(apiendpoint=check.api_endpoint)
    appres = '''
    [
        {
            "customer": 1000,
            "name": "Pulsar community",
            "community": true,
            "appid": "1xy4sn3",
            "active": true,
            "jobs_per_transaction": 2
        }
    ]
    '''
    jobres = '''
    [
        {
            "customer": 1000,
            "typeid": "latency",
            "name": "CDN Latency - Cloudflare",
            "community": true,
            "jobid": "1xtvhvx",
            "appid": "1xy4sn3",
            "active": true
        }
    ]
    '''

    requests_mock.get(url, text=appres)
    url1 = "{apiendpoint}/v1/pulsar/apps/1xy4sn3/jobs".format(apiendpoint=check.api_endpoint)
    requests_mock.get(url1, text=jobres)
    check.get_pulsar_applications()

    checkUrl = check.create_url(check.metrics, check.query_params)

    assert check.get_pulsar_job_name_from_id("1xtvhvx") == "CDN Latency - Cloudflare"
    # if check.query_params:
    query_params = check.query_params
    query_string = "?"
    query_string = query_string + "period=" + query_params["pulsar_period"] + "&"
    query_string = query_string + "geo=" + query_params["pulsar_geo"] + "&"
    query_string = query_string + "asn=" + query_params["pulsar_asn"] + "&"
    query_string = query_string[:-1]
    assert query_string == "?period=1m&geo=*&asn=*"
    assert check.query_params["pulsar_period"] == "1m"

    assert len(checkUrl) > 0
    assert check.api_endpoint is not None
    # qps
    assert checkUrl["qps"][0] == "https://my.nsone.net/v1/stats/qps"
    assert checkUrl["qps.dloc.com"][0] == "https://my.nsone.net/v1/stats/qps/dloc.com"
    # usage

    # ttl
    assert checkUrl["account.ttl.dloc.com"][0] == "https://my.nsone.net/v1/zones/dloc.com"
    assert checkUrl["account.ttl.dloc.com"][2] == ["record:dloc.com"]

    # pulsar
    expect = "https://my.nsone.net/v1/pulsar/query/decision/customer?period=2d&geo=*&asn=*"
    assert checkUrl["pulsar.decisions"][0] == expect
    # pulsar by app
    expect = "https://my.nsone.net/v1/pulsar/apps/1xy4sn3/jobs/1xtvhvx/data?period=1m"
    assert checkUrl["pulsar.performance.1xy4sn3.1xtvhvx"][0] == expect
    expect = "https://my.nsone.net/v1/pulsar/apps/1xy4sn3/jobs/1xtvhvx/availability?period=1m"
    assert checkUrl["pulsar.availability.1xy4sn3.1xtvhvx"][0] == expect

    # pulsar by record
    expect = "https://my.nsone.net/v1/pulsar/query/decision/record/www.dloc1.com/A?period=2d&geo=*&asn=*"
    assert checkUrl["pulsar.decisions.www.dloc1.com.A"][0] == expect
    expect = "https://my.nsone.net/v1/pulsar/query/routemap/hit/record/www.dloc1.com/A?period=2d&geo=*&asn=*"
    assert checkUrl["pulsar.routemap.hit.www.dloc1.com.A"][0] == expect


def test_get_pulsar_app(aggregator, instance, requests_mock):
    check = Ns1Check('ns1', {}, [instance])
    url = "{apiendpoint}/v1/pulsar/apps".format(apiendpoint=check.api_endpoint)
    appres = '''
    [
        {
            "customer": 1000,
            "name": "Pulsar community",
            "community": true,
            "appid": "1xy4sn3",
            "active": true,
            "jobs_per_transaction": 2
        }
    ]
    '''
    jobres = '''
    [
        {
            "customer": 1000,
            "typeid": "latency",
            "name": "CDN Latency - Cloudflare",
            "community": true,
            "jobid": "1xtvhvx",
            "appid": "1xy4sn3",
            "active": true
        }
    ]
    '''

    requests_mock.get(url, text=appres)
    url1 = "{apiendpoint}/v1/pulsar/apps/1xy4sn3/jobs".format(apiendpoint=check.api_endpoint)
    requests_mock.get(url1, text=jobres)
    pulsar_apps = check.get_pulsar_applications()

    assert len(pulsar_apps) > 0
    key = next(iter(pulsar_apps))
    assert pulsar_apps[key][0] == "Pulsar community"
    assert pulsar_apps["1xy4sn3"][0] == "Pulsar community"
    jobs = pulsar_apps[key][1]
    assert jobs[0]["jobid"] == "1xtvhvx"


USAGE_RESULT = """
[
    {
        "jobs": 1,
        "graph": [
            [
                1619217000,
                1408
            ],
            [
                1619218800,
                1410
            ],
            [
                1619220600,
                758
            ]
        ],
        "period": "1h",
        "zones": 8,
        "records": 23,
        "queries": 3576,
        "feeds": 3
    }
]
"""

PULSAR_RESULT_DECISIONS = """
{
    "graphs": [
        {
            "graph": [
                [
                    1619740800,
                    1890.0
                ],
                [
                    1619784000,
                    4090.0
                ],
                [
                    1619827200,
                    1644.0
                ],
                [
                    1619870400,
                    3275.0
                ]
            ],
            "tags": {
                "asn": "16509",
                "result": "OK",
                "jobid": "1b1o94j"
            }
        },
        {
            "graph": [
                [
                    1619740800,
                    2955.0
                ],
                [
                    1619784000,
                    2064.0
                ],
                [
                    1619827200,
                    7167.0
                ],
                [
                    1619870400,
                    1901.0
                ]
            ],
            "tags": {
                "asn": "16509",
                "result": "OK",
                "jobid": "1xtvhvx"
            }
        },
        {
            "graph": [
                [
                    1619740800,
                    5293.0
                ],
                [
                    1619784000,
                    3022.0
                ],
                [
                    1619827200,
                    969.0
                ],
                [
                    1619870400,
                    2976.0
                ]
            ],
            "tags": {
                "asn": "16509",
                "result": "OK",
                "jobid": "1xtsor1"
            }
        }
    ],
    "end_ts": 1619908667,
    "start_ts": 1619735867
}
"""

PULSAR_RESULT_PERFORMANCE = """
{
    "agg": "p50",
    "graph": {
        "*": {
            "*": [
                [
                    1619827200,
                    48.32
                ],
                [
                    1619870400,
                    48.094
                ],
                [
                    1619913600,
                    48.255
                ],
                [
                    1619956800,
                    46.605
                ]
            ]
        }
    },
    "end_ts": 1619986378,
    "start_ts": 1619813578,
    "jobid": "1xtvhvx",
    "appid": "1xy4sn3"
}
"""

PULSAR_RESULT_AVAILABILITY = """
{
    "graphs": [
        {
            "graph": [
                [
                    1619827200,
                    1.0
                ],
                [
                    1619870400,
                    1.0
                ],
                [
                    1619913600,
                    1.0
                ],
                [
                    1619956800,
                    0.975
                ]
            ],
            "tags": {
                "instid": "1"
            }
        }
    ],
    "end_ts": 1619987103,
    "start_ts": 1619814303
}
"""


def test_usage_count(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    check.usage_count = {"test": [0, 0]}
    usage, status = check.extract_usage_count("test", json.loads(USAGE_RESULT))

    assert usage == 758
    assert status
    assert check.usage_count["test"] == [1619220600, 758]


def test_pulsar_count(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    check.usage_count = {"test": [0, 0]}
    usage, status = check.extract_pulsar_count("test", json.loads(PULSAR_RESULT_DECISIONS))

    assert usage == 8152
    assert status
    assert check.usage_count["test"] == [1619870400, 8152]

    check.usage_count = {"test": [1619870400, 5000]}
    usage, status = check.extract_pulsar_count("test", json.loads(PULSAR_RESULT_DECISIONS))
    assert usage == 3152
    assert check.usage_count["test"] == [1619870400, 8152]


def test_extractPulsarResponseTime(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    rtime, status = check.extract_pulsar_response_time(json.loads(PULSAR_RESULT_PERFORMANCE))
    assert rtime == 46.605
    assert status


def test_extractPulsarAvailabilityPercent(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    up_percent, status = check.extract_pulsar_availability(json.loads(PULSAR_RESULT_AVAILABILITY))
    assert up_percent == 0.975
    assert status


def test_read_prev_usage_count(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    check.usage_count_path = "./log"
    check.usage_count_fname = 'ns1_usage_count.txt'
    check.get_usage_count()
    assert check.usage_count["usage"] == [0, 0]


def test_remove_prefix(aggregator, instance_1):
    check = Ns1Check('ns1', {}, [instance_1])
    assert check.remove_prefix("prefix_text", "prefix_") == "text"
    assert check.remove_prefix("text", "noprefix_") == "text"
