
from typing import Any

from datadog_checks.base import AgentCheck

# from datadog_checks.base.utils.db import QueryManager
# from requests.exceptions import ConnectionError, HTTPError, InvalidURL, Timeout
# from json import JSONDecodeError


class Ns1Check(AgentCheck):
    NS1_SERVICE_CHECK = "ns1.can_connect"

    def __init__(self, name, init_config, instances):
        # super(Ns1Check, self).__init__(name, init_config, instances)

        # If the check is going to perform SQL queries you should define a query manager here.
        # More info at
        # https://datadoghq.dev/integrations-core/base/databases/#datadog_checks.base.utils.db.core.QueryManager
        # sample_query = {
        #     "name": "sample",
        #     "query": "SELECT * FROM sample_table",
        #     "columns": [
        #         {"name": "metric", "type": "gauge"}
        #     ],
        # }
        # self._query_manager = QueryManager(self, self.execute_query, queries=[sample_query])
        # self.check_initializations.append(self._query_manager.compile_queries)
        pass

    def check(self, _):
        # type: (Any) -> None
        # The following are useful bits of code to help new users get started.

        # Use self.instance to read the check configuration
        url = self.instance.get("url")

        # Perform HTTP Requests with our HTTP wrapper.
        # More info at https://datadoghq.dev/integrations-core/base/http/
        # try:
        #     response = self.http.get(url)
        #     response.raise_for_status()
        #     response_json = response.json()

        

        # This is how you submit metrics
        # There are different types of metrics that you can submit (gauge, event).
        # More info at https://datadoghq.dev/integrations-core/base/api/#datadog_checks.base.checks.base.AgentCheck
        self.gauge("test", 1.23, tags=['foo:bar'])

        # Perform database queries using the Query Manager
        # self._query_manager.execute()

        # This is how you use the persistent cache. This cache file based and persists across agent restarts.
        # If you need an in-memory cache that is persisted across runs
        # You can define a dictionary in the __init__ method.
        # self.write_persistent_cache("key", "value")
        # value = self.read_persistent_cache("key")

        # If your check ran successfully, you can send the status.
        # More info at
        # https://datadoghq.dev/integrations-core/base/api/#datadog_checks.base.checks.base.AgentCheck.service_check
        # self.service_check("ns1.can_connect", AgentCheck.OK)

        pass

    def getStats(self, url):
        try:
            response = self.http.get(url)
            response.raise_for_status()
            response_json = response.json()
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

        except JSONDecodeError as e:
            self.service_check(
                self.NS1_SERVICE_CHECK,
                AgentCheck.CRITICAL,
                message="JSON Parse failed: {}, {}".format(url, e),
            )
            raise

        except ValueError as e:
            self.service_check(
                self.NS1_SERVICE_CHECK, AgentCheck.CRITICAL, message=str(e)
            )
            raise
        except Exception:
            self.service_check(self.NS1_SERVICE_CHECK, AgentCheck.CRITICAL, message = "Error getting stats frmo NS1 DNS")
            raise

        
        return response_json

    def SendMetrics(self, metricName, metricValue):
        self.gauge('ns1.{}'.format(metricName), metricValue)
