# Copyright (c) 2016 Mirantis, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import itertools
import time

import logging
from oslo_utils import excutils

from kuryr_kubernetes import exceptions
from kuryr_kubernetes.handlers import base
from kuryr_kubernetes import utils

LOG = logging.getLogger(__name__)


class Retry(base.EventHandler):
    """Retries handler on failure.

    `Retry` can be used to decorate another `handler` to be retried whenever
    it raises any of the specified `exceptions`. If the `handler` does not
    succeed within the time limit specified by `timeout`, `Retry` will
    raise the exception risen by `handler`. `Retry` does not interrupt the
    `handler`, so the actual time spent within a single call to `Retry` may
    exceed the `timeout` depending on responsiveness of the `handler`.

    `handler` is retried for the same `event` (expected backoff E(c) =
    interval * 2 ** c / 2).
    """

    def __init__(self, handler, exceptions=Exception,
                 timeout=utils.DEFAULT_TIMEOUT,
                 interval=utils.DEFAULT_INTERVAL):
        self._handler = handler
        self._exceptions = exceptions
        self._timeout = timeout
        self._interval = interval

    def __call__(self, event):
        deadline = time.time() + self._timeout
        for attempt in itertools.count(1):
            try:
                self._handler(event)
                break
            except self._exceptions:
                with excutils.save_and_reraise_exception() as ex:
                    if self._sleep(deadline, attempt, ex.value):
                        ex.reraise = False
                    else:
                        LOG.debug('Report handler unhealthy %s', self._handler)
                        self._handler.set_health_status(healthy=False)
            except Exception:
                LOG.exception('Report handler unhealthy %s', self._handler)
                self._handler.set_health_status(healthy=False)
                raise

    def _sleep(self, deadline, attempt, exception):
        LOG.debug("Handler %s failed (attempt %s; %s)",
                  self._handler, attempt, exceptions.format_msg(exception))
        interval = utils.exponential_sleep(deadline, attempt,
                                           self._interval)
        if not interval:
            LOG.debug("Handler %s failed (attempt %s; %s), "
                      "timeout exceeded (%s seconds)",
                      self._handler, attempt, exceptions.format_msg(exception),
                      self._timeout)
            return 0

        LOG.debug("Resumed after %s seconds. Retry handler %s", interval,
                  self._handler)
        return interval
