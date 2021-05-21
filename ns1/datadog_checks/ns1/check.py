import errno
import json
import os

from requests.exceptions import ConnectionError, HTTPError, InvalidURL, Timeout

from datadog_checks.base import AgentCheck, ConfigurationError

from .ns1_url_utils import Ns1Url


class Ns1Check(AgentCheck):
    NS1_SERVICE_CHECK = "ns1.can_connect"

    def __init__(self, name, init_config, instances):
        super(Ns1Check, self).__init__(name, init_config, instances)
        self.api_endpoint = self.instance.get("api_endpoint")
        if not self.api_endpoint:
            raise ConfigurationError('NS1 API endpoint must be specified in configuration')

        self.api_key = self.instance.get("api_key")
        if not self.api_key:
            raise ConfigurationError('NS1 API key must be specified in configuration')

        self.headers = {"X-NSONE-Key": self.api_key}

        self.metrics = self.instance.get("metrics")
        if not self.metrics or len(self.metrics) == 0:
            raise ConfigurationError('Invalid metrics config!')

        self.query_params = self.instance.get("query_params")
        self.usage_count_path = "/opt/datadog-agent/log"
        self.usage_count_fname = 'ns1_usage_count.txt'
        self.ns1 = Ns1Url(self.api_endpoint)
        self.pulsar_apps = {}

    def check(self, instance):
        self.log.info('Startup')

        # get counters from previous run
        self.get_usage_count()

        # create URLs to query API for all configured metrics
        checkUrl = self.create_url(self.metrics, self.query_params)

        for k, v in checkUrl.items():
            try:
                url, name, tags, metric_type = v
                # Query API to get metrics
                res = self.get_stats(url)
                self.log.info('NS1 API result', extra={'result': res})
                self.log.info(json.dumps(res))
                if res:
                    # extract metric from API result.
                    val, status = self.extract_metric(k, res)
                    # send metric to datadog if extraction was sucessful
                    if status:
                        self.send_metrics(name, val, tags, metric_type)
            except Exception:
                raise
        # save counters for next run
        self.set_usage_count()
        msg = 'NS1 metrics check run for NS1 API endpoint %s was successful' % self.api_endpoint
        self.service_check(self.NS1_SERVICE_CHECK, AgentCheck.OK, message=msg)

    def get_pulsar_job_name_from_id(self, pulsar_job_id):
        for _, v in self.pulsar_apps.items():
            for job in v[1]:
                jobid = job["jobid"]
                if jobid == pulsar_job_id:
                    jobname = job["name"]
                    return jobname
        return ""

    def create_url(self, metrics, query_params):
        # create dictionary with metrics name and url to check for all configured metrics in conf.yaml file
        checkUrl = {}

        for key, val in metrics.items():
            if key == "qps":
                checkUrl.update(self.ns1.get_stats_url(key, val, query_params))
            elif key == "usage":
                checkUrl.update(self.ns1.get_stats_url(key, val, query_params))
            elif key == "account":
                checkUrl.update(self.ns1.get_zone_info_url(key, val))
                checkUrl.update(self.ns1.get_plan_details_url(key, val))
            elif key == "ddi":
                if val:
                    scopegroups = self.get_ddi_scope_groups()
                else:
                    scopegroups = None
                checkUrl.update(self.ns1.get_ddi_url(key, val, scopegroups))
            elif key == "pulsar":
                checkUrl.update(self.ns1.get_pulsar_url(query_params))
            elif key == "pulsar_by_app":
                self.pulsar_apps = self.get_pulsar_applications()
                checkUrl.update(self.ns1.get_pulsar_by_app_url(val, self.pulsar_apps, query_params))
            elif key == "pulsar_by_record":
                checkUrl.update(self.ns1.get_pulsar_by_record_url(val, query_params))

        return checkUrl

    def get_ddi_scope_groups(self):
        url = "{apiendpoint}/v1/dhcp/scopegroup".format(apiendpoint=self.api_endpoint)
        res = self.get_stats(url)
        scopegroups = {}
        for group in res:
            group_id = group["id"]
            group_name = group["name"]
            scopegroups[group_id] = group_name
        return scopegroups

    def get_usage_count(self):

        try:
            os.makedirs(self.usage_count_path)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        fullname = os.path.join(self.usage_count_path, self.usage_count_fname)

        self.usage_count = {"usage": [0, 0]}
        if os.path.isfile(fullname):
            with open(fullname, 'r+') as f:
                self.usage_count = json.load(f)
        else:
            with open(fullname, 'w+') as f:
                json.dump(self.usage_count, f)

    def set_usage_count(self):

        fullname = '/opt/datadog-agent/log/ns1_usage_count.txt'

        if os.path.isfile(fullname):
            with open(fullname, 'w+') as f:
                json.dump(self.usage_count, f)

    def extract_metric(self, key, result):
        # Various NS1 APis are returning different data structures, extract values depending on which API was called
        try:
            if "qps" in key:
                res = result["qps"]
                status = True
            elif "usage" in key or "leases" in key:
                # usage and leases api result have same structure
                res, status = self.extract_usage_count(key, result)
            elif "billing" in key:
                res, status = self.extract_billing(result)
            elif "ttl" in key:
                res, status = self.extract_records_ttl(result)
            elif "pulsar.performance" in key:
                res, status = self.extract_pulsar_response_time(result)
            elif "pulsar.availability" in key:
                res, status = self.extract_pulsar_availability(result)
            elif "pulsar.decisions" == key:
                res, status = self.extract_pulsar_count_by_job(key, result)
            elif "pulsar" in key:
                res, status = self.extract_pulsar_count(key, result)
            elif "peak_lps" in key:
                # usage, leases and lps api result have same structure
                res, status = self.extract_peak_lps(result)

            return res, status
        except Exception:
            return None, False

    def get_pulsar_applications(self):
        url = "{apiendpoint}/v1/pulsar/apps".format(apiendpoint=self.api_endpoint)
        res = self.get_stats(url)
        apps = {}
        for app in res:
            url = url + "/{app_id}/jobs".format(app_id=app["appid"])
            jobs = self.get_stats(url)
            apps[app["appid"]] = [app["name"], jobs]
        return apps

    def extract_pulsar_count_by_job(self, key, jsonResult):
        try:
            graphs = jsonResult["graphs"]
            # this is called for each url in checkUrl dictionary
            # get last timestamp and count from self.usage_count
            # make sure decisions are queried with period of 2d in order to get sumarry per 12 hours,
            # so then we can just take last bucket and check count
            curr_timestamp = 0
            curr_count = 0
            result = {}

            for element in graphs:
                graph = element["graph"]
                jobtags = element["tags"]
                jobid = jobtags["jobid"]
                # sort graph array
                # find last timestamp that is >= last time stamp saved in file
                res = sorted(graph, key=lambda x: x[0], reverse=True)
                if res and len(res) > 0:

                    curr_timestamp = res[0][0]
                    curr_count = res[0][1]

                    # find this metric in usage count
                    jobkey = key + "." + jobid
                    if jobkey in self.usage_count:
                        prev_timestamp = self.usage_count[jobkey][0]
                        prev_count = self.usage_count[jobkey][1]
                        if curr_timestamp == prev_timestamp:
                            # don't submit count if it didn't increase
                            if curr_count >= prev_count:
                                self.usage_count[jobkey] = [prev_timestamp, curr_count]
                                result[jobkey] = curr_count - prev_count
                            else:
                                result[jobkey] = 0
                        else:
                            self.usage_count[jobkey] = [curr_timestamp, curr_count]
                            result[jobkey] = curr_count
                    else:
                        self.usage_count[jobkey] = [curr_timestamp, curr_count]
                        result[jobkey] = curr_count

            return result, True
        except Exception:
            return None, False

    def extract_pulsar_count(self, key, jsonResult):
        try:
            graphs = jsonResult["graphs"]
            # get last timestamp and count from self.usage_count
            curr_timestamp = 0
            curr_count = 0

            # sum count for all elements in array, make sure last time stamp is the same
            # if timestamp is not the same, skip this submission, it's right at the time
            # buckets are being closed so reporting might be off for a few seconds,
            # will pick it up on next run
            index = 0
            for element in graphs:
                graph = element["graph"]
                # sort graph array
                # find last timestamp that is >= last time stamp saved in file
                res = sorted(graph, key=lambda x: x[0], reverse=True)
                if res and len(res) > 0:
                    if index == 0:
                        curr_timestamp = res[0][0]
                        index = -1
                    if curr_timestamp != res[0][0]:
                        return None, False
                    curr_count = curr_count + res[0][1]

            # find this metric in usage count
            if key in self.usage_count:
                prev_timestamp = self.usage_count[key][0]
                prev_count = self.usage_count[key][1]
                if curr_timestamp == prev_timestamp:
                    if curr_count >= prev_count:
                        self.usage_count[key] = [prev_timestamp, curr_count]
                        result = curr_count - prev_count
                    else:
                        result = 0
                else:
                    self.usage_count[key] = [curr_timestamp, curr_count]
                    result = curr_count
            else:
                self.usage_count[key] = [curr_timestamp, curr_count]
                result = curr_count

            return result, True
        except Exception:
            return None, False

    def extract_pulsar_response_time(self, jsonResult):
        try:
            geo = "*"
            asn = "*"
            if self.query_params:
                if "pulsar_geo" in self.query_params:
                    geo = self.query_params["pulsar_geo"]
                if "pulsar_asn" in self.query_params:
                    asn = self.query_params["pulsar_asn"]

            graph = jsonResult["graph"]
            data = graph[geo][asn]
            res = sorted(data, key=lambda x: x[0], reverse=True)
            response_time = res[0][1]
            return response_time, True
        except Exception:
            return None, False

    def extract_pulsar_availability(self, jsonResult):
        try:
            graphs = jsonResult["graphs"]
            for element in graphs:
                graph = element["graph"]
                res = sorted(graph, key=lambda x: x[0], reverse=True)
                if res and len(res) > 0:
                    percent_available = res[0][1]
                    return percent_available, True
                else:
                    return None, False
        except Exception:
            return None, False

    def extract_peak_lps(self, jsonResult):
        try:
            graph = jsonResult[0]["graph"]
            res = sorted(graph, key=lambda x: x[0], reverse=True)
            curr_lps = res[0][1]
            return curr_lps, True

        except Exception:
            return None, False

    def extract_usage_count(self, key, jsonResult):

        try:
            graph = jsonResult[0]["graph"]
            # usage api will return array of dictionaries, we want to get 'graph' object
            # which in turn is list of lists, each element being [timestamp, query_count]
            # so, get last query count from result.
            # Sort by timestamp descending order to make sure we get latest
            res = sorted(graph, key=lambda x: x[0], reverse=True)

            curr_timestamp = res[0][0]
            curr_count = res[0][1]
            # find this metric in usage count
            if key in self.usage_count:
                prev_timestamp = self.usage_count[key][0]
                prev_count = self.usage_count[key][1]
                if curr_timestamp == prev_timestamp:
                    if curr_count >= prev_count:
                        self.usage_count[key] = [prev_timestamp, curr_count]
                        result = curr_count - prev_count
                    else:
                        result = 0
                else:
                    self.usage_count[key] = [curr_timestamp, curr_count]
                    result = curr_count
            else:
                self.usage_count[key] = [curr_timestamp, curr_count]
                result = curr_count

            return result, True
        except Exception:
            return None, False

    def extract_records_ttl(self, jsonResult):
        try:
            zoneTtl = {}
            for zone in jsonResult["records"]:
                zoneTtl[zone["domain"]] = zone["ttl"]
            return zoneTtl, True
        except Exception:
            return None, False

    def extract_billing(self, jsonResult):
        try:
            billing = {}
            billing["usage"] = jsonResult["totals"]["queries"]
            billing["limit"] = jsonResult["any"]["query_credit"]
            return billing, True
        except Exception:
            return None, False

    def get_stats(self, url):
        # Perform HTTP Requests with our HTTP wrapper.
        # More info at https://datadoghq.dev/integrations-core/base/http/
        try:
            response = self.http.get(url, extra_headers=self.headers)
            response.raise_for_status()
            response_json = response.json()

            return response_json

        except Timeout as e:
            self.service_check(
                self.NS1_SERVICE_CHECK,
                AgentCheck.CRITICAL,
                message="Request timeout: {}, {}".format(url, e),
            )
            raise

        except (HTTPError, InvalidURL, ConnectionError) as e:
            self.service_check(
                self.NS1_SERVICE_CHECK,
                AgentCheck.CRITICAL,
                message="Request failed: {}, {}".format(url, e),
            )
            raise

        except ValueError as e:
            self.service_check(self.NS1_SERVICE_CHECK, AgentCheck.CRITICAL, message=str(e))
            raise
        except Exception:
            self.service_check(self.NS1_SERVICE_CHECK, AgentCheck.CRITICAL, message="Error getting stats from NS1 DNS")
            raise

    def remove_prefix(self, text, prefix):
        if text.startswith(prefix):
            return text[len(prefix) :]
        return text

    def send_metrics(self, metric_name, metric_value, tags, metric_type):
        if metric_name == "billing":
            for k, v in metric_value.items():
                # {"usage": 1234, "limit": 500000}
                # tag as either usage or limit
                tags = ["billing:{btype}".format(btype=k)]
                if metric_type == "gauge":
                    self.gauge('ns1.billing', v, tags)
                elif metric_type == "count":
                    self.count('ns1.billing', v, tags)
        elif metric_name == "pulsar.decisions":
            for k, v in metric_value.items():
                pulsar_job_id = self.remove_prefix(k, "pulsar.decisions.")
                tags = ["resource:{jobname}".format(jobname=self.get_pulsar_job_name_from_id(pulsar_job_id))]
                if metric_type == "gauge":
                    self.gauge('ns1.{name}'.format(name=metric_name), v, tags)
                elif metric_type == "count":
                    self.count('ns1.{name}'.format(name=metric_name), v, tags)
        elif isinstance(metric_value, dict):
            for k, v in metric_value.items():
                # All by record metric will have result as dictionsry
                # add tag by DNS record
                tags = ["record:{domain}".format(domain=k)]
                if metric_type == "gauge":
                    self.gauge('ns1.{name}'.format(name=metric_name), v, tags)
                elif metric_type == "count":
                    self.count('ns1.{name}.{record}'.format(name=metric_name, record=k), v, tags)
        else:
            # scalar value, just submit
            if metric_type == "gauge":
                self.gauge('ns1.{}'.format(metric_name), metric_value, tags)
            elif metric_type == "count":
                self.count('ns1.{}'.format(metric_name), metric_value, tags)
