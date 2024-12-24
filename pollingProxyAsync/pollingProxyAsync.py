import json
from typing import Dict, List, Callable, Any
import time
from aiohttp.client import ClientSession, ClientResponse
import random
import asyncio
from .types import _InterfacePollingSettings, _InterfaceProxy, _InterfaceUrls, UnifiedData, Pair


class PollingProxyAsync:
    # Instance variables are initialized in __init__
    def __init__(self, settings: _InterfacePollingSettings, urls: _InterfaceUrls, proxies: _InterfaceProxy):
        self.settings = settings
        self.urls = urls
        self.proxies = proxies
        self.timeout = settings.timeout

        # Initialize instance variables
        self.pairs_not_used = {}
        self.pairs_used_refreshed = {}
        self.pairs_used_not_processed = asyncio.Queue()
        self.sessions = {}  # Will store sessions as {url: {proxy: session}}
        self.tiers_dict = {}
        self.tasks_lock = asyncio.Lock()
        self.tasks: list = []

        self._map_one_request = int(settings.map_one_request)
        self._sleep_between_iterations = float(settings.sleep_between_iterations)
        
        # self._func_make_request = settings.func_make_request

        # {"data": data|error, "success": bool, "type": "catched"|"json"}
        self._func_find_error = settings.func_find_error
        self._func_process_responce = settings.func_process_responce
        self._func_process_failure = settings.func_process_failure
        
        self._headers = settings.headers
        self._errors_max_per_N_s = settings.errors_max_per_N_s
        self._errors_N_s = settings.errors_N_s

        self._urls = urls.urls
        self._proxies = dict(proxies.proxies)
        self._tiers = settings.tiers

        self._list_urls = list(self._urls.keys())

        self._generate_pairs()
        self._generate_tiers()

    async def add_tasks(self, data):
        async with self.tasks_lock:
            self.tasks.extend(data)

    def _generate_tiers(self):
        for tier in self._tiers:
            self.tiers_dict[tier] = float(tier)
        
    def _generate_pairs(self):
        for url in self._urls:
            self.pairs_not_used[url] = []
            self.pairs_used_refreshed[url] = {tier: [] for tier in self._tiers}
            for proxy in self._proxies:
                if proxy in self._urls[url]['ignore_proxies']:
                    continue
                if url in self._proxies[proxy]['ignore_urls']:
                    continue
                self.pairs_not_used[url].append({
                    "proxy": proxy, 
                    "url": url, 
                    "errors_start": [], 
                    "errors_max_per_N_s": self._errors_max_per_N_s,
                    "errors_N_s": self._errors_N_s,
                    "errors": [],
                    "requests_start": [], 
                    "last_error": None,
                    "maxReqsPerNSec": self._urls[url]['maxReqsPerNSec'],
                    "NSec": self._urls[url]['NSec'],
                    "last_time": .0,
                    "tier": "0.5",
                    "average": .0,
                    "concurent_requests": self._proxies[proxy]['concurent_requests'],
                })
            random.shuffle(self.pairs_not_used[url])

    async def start(self):
        self._running = True  # Flag to control the loop
        try:
            while self._running:
                await self._iteration()
                await asyncio.sleep(self._sleep_between_iterations)
        except asyncio.CancelledError:
            pass  # Allow the loop to be cancelled
        finally:
            await self.close_sessions()

    async def stop(self):
        self._running = False
        

    async def _iteration(self):
        await self._process_used()
        async with self.tasks_lock:
            pairs_list = await self._find_pairs_for_n(len(self.tasks))
            # #print(pairs_list)
            tasks = self.tasks
            if self.settings.tasks_one_time:
                self.tasks = []

        for task_index, task in enumerate(tasks):
            #print("doing")
            if task_index < len(pairs_list):
                pair_list = pairs_list[task_index]
                for pair in pair_list:
                    #print("creating task")
                    asyncio.create_task(self._make_and_process(pair, task))
            else:
                # Handle case where no pairs are available
                pass
        # Do not clear self.tasks

    async def _make_and_process(self, pair: Pair, data: Any):
        #print("before resp")
        resp = await self._make_request_pair(pair, data)
        #print(resp)
        await self._func_process_responce(resp)
        
    # data?, headers?, timeout?
    async def _make_request_pair(self, pair, data=None, headers=None, timeout=None) -> UnifiedData:
        #print("triing maiking")
        # Create session only when the pair is used for the first time
        if pair['url'] not in self.sessions:
            self.sessions[pair['url']] = {}
        if pair['proxy'] not in self.sessions[pair['url']]:
            # Combine headers from URL and settings
            session_headers = self._urls[pair['url']]['headers'].copy()
            session_headers.update(self._headers)
            self.sessions[pair['url']][pair['proxy']] = ClientSession(headers=session_headers)
        #print("whata fuck")
        kwargs = {"timeout": timeout if timeout else self.timeout}
        # try:
        if headers:
            kwargs['headers'] = headers
        #print("fucking shit")
        time_start = time.time()
        #print("time start", time_start)
        try:
            if data:
                #print("data")
                async with self.sessions[pair["url"]][pair['proxy']].post(pair['url'], json=data, proxy=pair['proxy'], **kwargs) as responce:
                    udata: UnifiedData = await self._func_find_error(responce, data)
            else:
                async with self.sessions[pair["url"]][pair['proxy']].get(pair['url'], proxy=pair['proxy'], **kwargs) as responce:
                    udata: UnifiedData = await self._func_find_error(responce, data)
        except Exception as e:
            time_end = time.time()
            pair['errors_start'].append(time_start)
            pair['last_time'] = time_end - time_start
            pair['last_error'] = e
            await self.pairs_used_not_processed.put(pair)
            udata: UnifiedData = {"data": e, "success": False, "type": "catched", "payload": data}
            return udata
        time_end = time.time()
        pair['last_time'] = time_end - time_start
        if udata.get('success'):
            pair['requests_start'].append(time_start)
            await self.pairs_used_not_processed.put(pair)
            return udata
        else:
            pair['last_error'] = udata
            pair['errors_start'].append(time_start)
            await self.pairs_used_not_processed.put(pair)
            return udata

    async def _process_used(self):
        pairs: List[Pair] = []
        while not self.pairs_used_not_processed.empty():
            item = await self.pairs_used_not_processed.get()
            pairs.append(item)
        time_now = time.time()
        for pair in pairs:
            errors_to_remove = []
            for error in pair['errors_start']:
                if error < time_now - pair["errors_N_s"]:
                    errors_to_remove.append(error)
            for error in errors_to_remove:
                pair['errors_start'].remove(error)
            if pair['errors_max_per_N_s'] > 0 and len(pair['errors_start']) >= pair['errors_max_per_N_s']:
                if await self._func_process_failure(pair):
                    self.pairs_not_used[pair['url']].append(pair)
                continue

            reqs_to_remove = []
            for req in pair['requests_start']:
                if req < time_now - pair['NSec']:
                    reqs_to_remove.append(req)
            for req in reqs_to_remove:
                pair['requests_start'].remove(req)
            if pair['maxReqsPerNSec'] > 0 and len(pair['requests_start']) >= pair['maxReqsPerNSec']:
                await self.pairs_used_not_processed.put(pair)
                continue

            pair['average'] = (pair['average'] + pair['last_time']) / 2 if pair['average'] != .0 else pair['last_time']
            
            found_tier = False
            for tier in self._tiers:
                if pair['average'] < self.tiers_dict[tier]:
                    pair['tier'] = tier
                    found_tier = True
                    break
            if not found_tier:
                self.pairs_not_used[pair['url']].append(pair)
                continue

            self.pairs_used_refreshed[pair['url']][pair['tier']].append(pair)

    # -> list(pair)
    async def _find_pairs_one_request(self):
        pairs: List[Pair] = []
        urls_found = []
        urls = self._list_urls.copy()
        random.shuffle(urls)

        ch_found = 0
        for url in urls:
            if ch_found >= self._map_one_request:
                break
            for tier in self.pairs_used_refreshed[url]:
                len_url_tier = len(self.pairs_used_refreshed[url][tier])
                if len_url_tier != 0:
                    i = random.randint(0, len_url_tier - 1)
                    urls_found.append(url)
                    pairs.append(self.pairs_used_refreshed[url][tier].pop(i))
                    ch_found += 1
                    break

        target = self._map_one_request - ch_found
        ch_target = 0
        if ch_found < self._map_one_request:
            urls_not_found = [url for url in urls if url not in urls_found]
            for url in urls_not_found:
                if ch_target >= target:
                    break
                if self.pairs_not_used[url]:
                    pair = self.pairs_not_used[url].pop(0)
                    pairs.append(pair)
                    ch_target += 1

        return pairs

    async def _find_pairs_for_n(self, n):
        result = []
        for i in range(n):
            pairs = await self._find_pairs_one_request()
            result.append(pairs)
        return result

    # Method to close all sessions
    async def close_sessions(self):
        for url_sessions in self.sessions.values():
            for session in url_sessions.values():
                await session.close()
        self.sessions.clear()
