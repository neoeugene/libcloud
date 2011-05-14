# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time

from libcloud.common.types import LibcloudError
from libcloud.utils import reverse_dict
from libcloud.common.gogrid import GoGridConnection, BaseGoGridDriver
from libcloud.loadbalancer.base import LoadBalancer, Member, Driver, Algorithm
from libcloud.loadbalancer.base import DEFAULT_ALGORITHM 
from libcloud.loadbalancer.types import Provider, State, LibcloudLBImmutableError


class GoGridLBDriver(BaseGoGridDriver, Driver):
    connectionCls = GoGridConnection
    type = Provider.RACKSPACE
    api_name = 'gogrid_lb'
    name = 'GoGrid LB'

    LB_STATE_MAP = { 'On': State.RUNNING,
                     'Unknown': State.UNKNOWN }
    _VALUE_TO_ALGORITHM_MAP = {
        'round balancer': Algorithm.ROUND_ROBIN,
        'least connection': Algorithm.LEAST_CONNECTIONS
    }
    _ALGORITHM_TO_VALUE_MAP = reverse_dict(_VALUE_TO_ALGORITHM_MAP)

    def list_balancers(self):
        return self._to_balancers(
                self.connection.request('/api/grid/loadbalancer/list').object)

    def ex_create_balancer_nowait(self, name, port, algorithm, members):
        if not algorithm:
            algorithm = DEFAULT_ALGORITHM
        else:
            algorithm = self._algorithm_to_value(algorithm)

        params = {'name': name,
                  'loadbalancer.type': algorithm,
                  'virtualip.ip': self._get_first_ip(),
                  'virtualip.port': port}
        params.update(self._members_to_params(members))

        resp = self.connection.request('/api/grid/loadbalancer/add',
                method='GET',
                params=params)
        return self._to_balancers(resp.object)[0]

    def create_balancer(self, name, port, algorithm, members):
        balancer = self.ex_create_balancer_nowait(name, port, algorithm, members)

        timeout = 60 * 20
        waittime = 0
        interval = 2 * 15

        if balancer.id is not None:
            return balancer
        else:
            while waittime < timeout:
                balancers = self.list_balancers()

                for i in balancers:
                    if i.name == balancer.name and i.id is not None:
                        return i

                waittime += interval
                time.sleep(interval)

        raise Exception('Failed to get id')

    def destroy_balancer(self, balancer):
        try:
            resp = self.connection.request('/api/grid/loadbalancer/delete',
                    method='POST', params={'id': balancer.id})
        except Exception as err:
            if "Update request for LoadBalancer" in str(err):
                raise LibcloudLBImmutableError("Cannot delete immutable object",
                        GoGridLBDriver)
            else:
                raise

        return resp.status == 200

    def get_balancer(self, **kwargs):
        params = {}

        try:
            params['name'] = kwargs['ex_balancer_name']
        except KeyError:
            balancer_id = kwargs['balancer_id']
            params['id'] = balancer_id

        resp = self.connection.request('/api/grid/loadbalancer/get',
                params=params)

        return self._to_balancers(resp.object)[0]

    def balancer_attach_member(self, balancer, member):
        members = self.balancer_list_members(balancer)
        members.append(member)

        params = {"id": balancer.id}

        params.update(self._members_to_params(members))

        resp = self._update_balancer(params)

        return [ m for m in
                self._to_members(resp.object["list"][0]["realiplist"])
                if m.ip == member.ip ][0]

    def balancer_detach_member(self, balancer, member):
        members = self.balancer_list_members(balancer)

        remaining_members = [n for n in members if n.id != member.id]

        params = {"id": balancer.id}
        params.update(self._members_to_params(remaining_members))

        resp = self._update_balancer(params)

        return resp.status == 200

    def balancer_list_members(self, balancer):
        resp = self.connection.request('/api/grid/loadbalancer/get',
                params={'id': balancer.id})
        return self._to_members(resp.object["list"][0]["realiplist"])

    def _update_balancer(self, params):
        try:
            return self.connection.request('/api/grid/loadbalancer/edit',
                    method='POST',
                    params=params)
        except Exception as err:
            if "Update already pending" in str(err):
                raise LibcloudLBImmutableError("Balancer is immutable", GoGridLBDriver)

        raise LibcloudError(value='Exception: %s' % str(err), driver=self)

    def _members_to_params(self, members):
        """
        Helper method to convert list of L{Member} objects
        to GET params.

        """

        params = {}

        i = 0
        for member in members:
            params["realiplist.%s.ip" % i] = member.ip
            params["realiplist.%s.port" % i] = member.port
            i += 1

        return params

    def _to_balancers(self, object):
        return [ self._to_balancer(el) for el in object["list"] ]

    def _to_balancer(self, el):
        lb = LoadBalancer(id=el.get("id"),
                name=el["name"],
                state=self.LB_STATE_MAP.get(
                    el["state"]["name"], State.UNKNOWN),
                ip=el["virtualip"]["ip"]["ip"],
                port=el["virtualip"]["port"],
                driver=self.connection.driver)
        return lb

    def _to_members(self, object):
        return [ self._to_member(el) for el in object ]

    def _to_member(self, el):
        member = Member(id=el["ip"]["id"],
                ip=el["ip"]["ip"],
                port=el["port"])
        return member
