import contextlib
import copy
from datetime import timedelta
from enum import Enum
from math import floor

from api.util import raise_if_exc
from wazuh import agent
from wazuh.core import utils
from wazuh.core.agent import WazuhDBQueryAgents
from wazuh.core.cluster.dapi.dapi import DistributedAPI
from wazuh.core.common import DECIMALS_DATE_FORMAT
from wazuh.core.exception import WazuhError


class SkippingException(Exception):
    """Custom exception to control phase skips.
    """
    pass


class AgentsReconnectionPhases(str, Enum):
    NOT_STARTED = "Not started"
    CHECK_NODES_STABILITY = "Check nodes stability"
    CHECK_PREVIOUS_RECONNECTIONS = "Check previous reconnections"
    CHECK_AGENTS_BALANCE = "Check agents balance"
    RECONNECT_AGENTS = "Reconnect agents"
    BALANCE_SLEEPING = "Sleeping"
    NOT_ENOUGH_NODES = "Not enough nodes"
    HALT = "Halt"


class AgentsReconnect:
    """Class that encapsulates everything related to the agent reconnection algorithm."""

    def __init__(self, logger, nodes, master_name, blacklisted_nodes, nodes_stability_threshold,
                 max_assignments_per_node) -> None:
        """Class constructor.

        Parameters
        ----------
        logger : Logger object
            Logger to use.
        nodes : list
            List of nodes in the environment.
        master_name : str
            Name of the master node.
        blacklisted_nodes : set
            Set of nodes that are not taken into account for the agents reconnection.
        nodes_stability_threshold : int
            Number of consecutive checks that must be successful to consider the environment stable.
        max_assignments_per_node : int
            Number of agents that can reconnect to the same cluster node at the same time.
        """
        # Logger
        self.logger = logger

        # Check nodes stability
        self.nodes = nodes
        self.master_name = master_name
        self.blacklisted_nodes = blacklisted_nodes
        self.previous_nodes = set()
        self.nodes_stability_counter = 0
        self.nodes_stability_threshold = nodes_stability_threshold

        # Timestamps
        self.last_nodes_stability_check = 0

        # Check previous balance
        self.env_status = {}
        self.lost_agents_percent = 0.1  # 10%

        # Check agents balance -> Provisional
        self.balance_counter = 0
        self.balance_threshold = 3

        # Reconnection phase
        self.max_assignments_per_node = max_assignments_per_node
        self.expected_rounds = 0
        self.round_counter = 0
        self.reconnection_timestamp = 0
        self.reconnected_agents = []

        # General
        self.current_phase = AgentsReconnectionPhases.NOT_STARTED

        # Provisional
        self.posbalance_sleep = 60
        self.agents_connection_delay = 30

    def wazuh_exception_handler(func):
        async def wrapper(self, *args, **kwargs):
            try:
                return await func(self, *args, **kwargs)
            except WazuhError as e:
                self.logger.error(f"Error in {func.__name__}: {e}")
                self.reset_counters()

                raise SkippingException from e

        return wrapper

    def reset_counters(self, node_name=None, hard_reset=True) -> None:
        """Reset all counters of the reconnection procedure.
        If the node is specified, it will be checked if it is on the blacklist.

        Parameters
        ----------
        node_name : str, optional
            Name of the node to be checked against the blacklist, by default None.
        hard_reset : bool
            Whether to reset all counters (including stability-related) or not.
        """
        if node_name not in self.blacklisted_nodes:
            if hard_reset:
                self.balance_counter = 0
                self.nodes_stability_counter = 0
            self.expected_rounds = 0
            self.round_counter = 0
            self.logger.debug("Reset all counters.")
        else:
            self.logger.debug(f"Disconnected {node_name} node, it is blacklisted, skipping counters reset.")

    async def check_nodes_stability(self) -> bool:
        """Function in charge of determining whether an environment is stable.

        To verify the stability, the function uses the consecutive verification
        of the number of nodes in the environment.

        Returns
        -------
        bool
            True if the environment is stable, False otherwise.
        """
        self.current_phase = AgentsReconnectionPhases.CHECK_NODES_STABILITY
        node_list = set(self.nodes.keys()).union({self.master_name}) - self.blacklisted_nodes

        if len(node_list) <= 1:
            self.reset_counters()
            self.previous_nodes = set()
            self.current_phase = AgentsReconnectionPhases.NOT_ENOUGH_NODES

            return False

        self.logger.debug(f"Current detected nodes: {node_list}.")
        self.last_nodes_stability_check = utils.get_utc_now()

        if self.previous_nodes == node_list or len(self.previous_nodes) == 0:
            if self.nodes_stability_counter < self.nodes_stability_threshold:
                self.nodes_stability_counter += 1
            if self.previous_nodes == set():
                self.previous_nodes = node_list.copy()
            if self.nodes_stability_counter >= self.nodes_stability_threshold:
                self.logger.info(f"Cluster is stable.")
                return True
            else:
                self.logger.info(f"Checking cluster stability "
                                 f"({self.nodes_stability_counter}/{self.nodes_stability_threshold}).")

        else:
            self.logger.info("Nodes changed, restarting cluster stability phase.")
            self.previous_nodes = node_list.copy()
            self.reset_counters()
            return False

        return False

    @wazuh_exception_handler
    async def get_reconnected_agents(self, agents_list) -> dict:
        """Check that the specified agents reconnected correctly after the request.

        Parameters
        ----------
        agents_list : list
            Agents to check.

        Returns
        -------
        dict
            Dictionary with IDs that satisfy the lastKeepAlive verification.
        """
        agent_query = WazuhDBQueryAgents(
            count=False, filters={"id": agents_list}, select={"id"},
            query=f"lastKeepAlive>{self.reconnection_timestamp + timedelta(seconds=self.agents_connection_delay)}")

        return agent_query.run()

    async def check_previous_reconnections(self) -> bool:
        """Check the agents status after the previous reconnection.

        Returns
        -------
        bool
            True if the agents are connected and the tolerance criteria are met or no agent has been reconnected,
            False otherwise.
        """
        self.current_phase = AgentsReconnectionPhases.CHECK_PREVIOUS_RECONNECTIONS
        # If no agent has been balanced in the previous iteration return True
        if self.env_status == {}:
            return True

        lost_agents_threshold = sum(len(info['agents']) for info in self.env_status.values()) * self.lost_agents_percent
        connected_agents = await self.get_reconnected_agents(self.reconnected_agents)
        connected_agents = connected_agents['items']
        if len(self.reconnected_agents) != len(connected_agents):
            lost_agents = []
            connected_agents = [d['id'] for d in connected_agents]
            lost_agents.extend(r_agent for r_agent in self.reconnected_agents if r_agent not in connected_agents)
            if len(lost_agents) >= lost_agents_threshold:
                self.logger.warning('Too many lost agents. Halting reconnection procedure.')
                self.logger.debug(f'Lost agents: {lost_agents}.')
                self.current_phase = AgentsReconnectionPhases.HALT
                return False

        return True

    @wazuh_exception_handler
    async def get_agents_balance(self) -> dict:
        """Function in charge of checking the balance of the agents.

        Returns
        -------
        dict
            Dictionary with the agents that are not balanced.
            The keys of the dictionary are the names of the nodes and the values are the agents.
        """
        async def need_balance() -> dict:
            """Get the number of active agents per node and the number of
            agents that exceed the average number of agents per node.

            Returns
            -------
            dict
                Dictionary with the agents that exceed the average number of
                agents per node and the total number of active agents of each node.
            """
            agents_count = {}
            total = 0
            for node in self.previous_nodes:
                agent_query = WazuhDBQueryAgents(count=True, filters={"status": "active", "node_name": node},
                                                 select={"id"})
                agent_query._get_total_items(add_filters=True)
                agents_count[node] = agent_query.total_items
                total += agent_query.total_items

            try:
                mean = floor(total / len(self.previous_nodes))
            except ZeroDivisionError:
                return {}

            unbalanced_agents = {}
            for node, agents in agents_count.items():
                difference = agents - mean
                if node not in unbalanced_agents.keys():
                    unbalanced_agents[node] = {}
                unbalanced_agents[node]['agents'] = 0
                unbalanced_agents[node]['total'] = agents
                if difference > 1:
                    unbalanced_agents[node]['agents'] = difference

            return unbalanced_agents

        async def get_agents(current_balance) -> dict:
            """Get the last X IDs of the agents that exceed the average number of agents per node.
            Modify the original dictionary by replacing the number of agents by their IDs.

            Parameters
            ----------
            current_balance : dict
                Dictionary with the number of active agents per node and
                the agents that exceed the average number of agents per node.

            Returns
            -------
            dict
                Dictionary with the IDs to reconnect and the number of active agents per node.
            """
            for node, info in current_balance.items():
                if info['agents'] > 0:
                    agent_query = WazuhDBQueryAgents(
                        count=False, filters={"status": "active", "node_name": node},
                        limit=info['agents'], sort={"fields": ["id"], "order": "desc"}, select=["id"])
                    current_balance[node]['agents'] = [info["id"] for info in agent_query.run()["items"]]
                else:
                    current_balance[node]['agents'] = []

            return current_balance

        self.current_phase = AgentsReconnectionPhases.CHECK_AGENTS_BALANCE
        need_balance = await need_balance()
        if need_balance == {}:
            return {}

        current_unbalanced_agents = await get_agents(need_balance)
        if all(info['agents'] == [] for info in current_unbalanced_agents.values()):
            self.logger.info('Agents are balanced in the cluster.')
            current_unbalanced_agents.clear()
            self.reset_counters(hard_reset=False)
        else:
            self.logger.info('Agents are not balanced in the cluster.')

        return current_unbalanced_agents

    async def balance_previous_conditions(self) -> None:
        """Controller function for the pre-reconnection phase of agents.
        This function encapsulates the entire phase prior to agent balancing.
        """
        if await self.check_previous_reconnections():
            self.env_status = await self.get_agents_balance()
            if self.env_status:
                self.logger.debug2(f"Agents that need to be reconnected: "
                                   f"{str({node: info['agents'] for node, info in self.env_status.items()})}.")
                self.reconnected_agents = await self.balance_agents(self.env_status, self.max_assignments_per_node)
                self.reconnection_timestamp = utils.get_utc_now()

    def get_current_phase(self) -> AgentsReconnectionPhases:
        """Return the current phase of the algorithm.

        Returns
        -------
        AgentsReconnectionPhases
        """
        return self.current_phase

    def get_nodes_stability_info(self) -> dict:
        """Return the information related to the phase nodes stability.

        Returns
        -------
        dict
        """
        with contextlib.suppress(AttributeError):
            self.last_nodes_stability_check = self.last_nodes_stability_check.strftime(DECIMALS_DATE_FORMAT)

        return {
            'nodes_stability_counter': self.nodes_stability_counter,
            'nodes_stability_threshold': self.nodes_stability_threshold,
            'last_nodes_stability_check': self.last_nodes_stability_check,
            'last_register_nodes': str(list(self.nodes.keys()) + [self.master_name]),
            'blacklisted_nodes': str(list(self.blacklisted_nodes)),
            'last_register_agents_nodes': str({node: info['agents'] for node, info in self.env_status.items()})
        }

    def to_dict(self) -> dict:
        """Returns the model properties as a dict.

        Returns
        -------
        dict
        """
        NotImplementedError("Not implemented yet")

    def predict_distribution(self, nodes_info, max_assignments_per_node, calculate_rounds=False) -> dict:
        """Predict how reconnected agents will be distributed.

        It predicts how many agents will connect to each node based on the current
        distribution of the cluster. To prevent many agents from connecting to the same node,
        this method will return the IDs to which the reconnection request should be sent so
        that the limitation established in 'max_assignments_per_node' is respected.

        If 'calculate_rounds=True', it will calculate how many rounds of 'max_assignments_per_node' agents
        will be needed in order to redistribute all agents.

        Parameters
        ----------
        nodes_info : dict
            Dict with workers names, list of agents connected to each one and number of active agents.
        max_assignments_per_node : int
            Number of agents that can reconnect to the same cluster node.
        calculate_rounds : bool
            Calculate how many reconnection rounds will be necessary.

        Returns
        -------
        dict
            Agents' IDs to reconnect and number of rounds necessary.
        """
        nodes_info_cpy = copy.deepcopy(nodes_info)
        agents_to_reconnect = []
        rounds = 1

        while True:
            biggest_node = max(nodes_info_cpy.keys(), key=lambda x: nodes_info_cpy[x]['total'])
            smallest_node = min(nodes_info_cpy.keys(), key=lambda x: nodes_info_cpy[x]['total'])

            if nodes_info_cpy[biggest_node]['total'] - nodes_info_cpy[smallest_node]['total'] <= 1:
                break
            elif nodes_info_cpy[smallest_node]['total'] >= \
                    nodes_info[smallest_node]['total'] + max_assignments_per_node * rounds:
                if not calculate_rounds:
                    break
                rounds += 1

            if not calculate_rounds:
                try:
                    agents_to_reconnect.append(nodes_info_cpy[biggest_node]['agents'].pop())
                except IndexError:
                    break
            nodes_info_cpy[biggest_node]['total'] -= 1
            nodes_info_cpy[smallest_node]['total'] += 1

        return {'agents': agents_to_reconnect, 'rounds': rounds}

    async def reconnect_agents(self, agents_to_reconnect) -> list:
        """Redistribute agents in cluster.

        Send reconnect requests to agents so they are redistributed. Redistribution only works
        if agents are connected through a load balancer configured as least_conn.

        Parameters
        ----------
        agents_to_reconnect : list
            Agents IDs to reconnect.

        Returns
        -------
        reconnected_agents : list
            Agents to whom a reconnection request was successfully sent.
        """
        dapi = DistributedAPI(f=agent.reconnect_agents, f_kwargs={'agent_list': agents_to_reconnect},
                              request_type='distributed_master', logger=self.logger)
        data = raise_if_exc(await dapi.distribute_function()).render()
        return data.get('data', {}).get('affected_items', [])

    async def balance_agents(self, nodes_info, max_assignments_per_node=100) -> list:
        """Balance agents in rounds.

        Determines how many rounds will be necessary to balance all agents, and sends
        reconnection requests to a variable number of agents depending on the current round.

        Parameters
        ----------
        nodes_info : dict
            Dict with workers names, list of agents connected to each one and number of active agents.
        max_assignments_per_node : int
            Number of agents that can reconnect to the same cluster node.

        Returns
        -------
        result : list
            Agents to whom a reconnection request was successfully sent.
        """
        result = []
        self.current_phase = AgentsReconnectionPhases.RECONNECT_AGENTS

        if self.expected_rounds == 0:
            self.expected_rounds = self.predict_distribution(nodes_info, max_assignments_per_node, True)['rounds']
            total_active_agents = sum([info['total'] for info in nodes_info.values()])
            total_agents_to_reconnect = sum([len(info['agents']) for info in nodes_info.values()])
            max_assigns = max(min(total_active_agents * 0.05, max_assignments_per_node), 1)
            agents_to_reconnect = self.predict_distribution(nodes_info, max_assigns)['agents']
            self.logger.info(f'It will take {self.expected_rounds} rounds to reconnect {total_agents_to_reconnect} '
                             f'agents. Starting a small test round for {len(agents_to_reconnect)} agents.')

        elif self.round_counter < self.expected_rounds:
            self.round_counter += 1
            agents_to_reconnect = self.predict_distribution(nodes_info, max_assignments_per_node)['agents']
            self.logger.info(f'Reconnecting agents (round {self.round_counter}/{self.expected_rounds}).')

        else:
            self.logger.warning(f'Expected number of agent reconnection rounds has been exceeded '
                                f'({self.round_counter + 1}/{self.expected_rounds}). Stopping this task.')
            self.current_phase = AgentsReconnectionPhases.HALT
            return result

        try:
            result = await self.reconnect_agents(agents_to_reconnect)
        except Exception:
            self.logger.error('Error while sending reconnection request to agents. Restarting task.')
            self.reset_counters()

        return result
