import json
from typing import Dict, List, Callable, Any, TypedDict, Literal
import time
from aiohttp.client import  ClientResponse
import random
import asyncio



class UnifiedData(TypedDict):
    success: bool
    data: Exception | Any
    payload: Any
    type: Literal["catched", "json"]
    
class Pair(TypedDict):
    proxy: str
    url: str
    errors_start: List 
    errors_max_per_N_s: int
    errors_N_s: float
    errors: List
    requests_start: List
    last_error: Any
    maxReqsPerNSec: int
    NSec: float
    last_time: float
    tier: str
    average: float
    concurent_requests: int

    
Payload = Any

TypeProxies = Dict[str, Dict[str, List[str] | int]]
class _InterfaceProxy:
    proxies: TypeProxies
    
    def __init__(self, proxies):
        if type(proxies) == str:
            with open(proxies) as file:
                try:
                    proxies = json.load(file)
                except:
                    proxies = file.read()
                    proxies = proxies.split("\n")

        if type(proxies) == list:
            self.proxies = {p: {"ignore_urls": [], "concurent_requests": 0} for p in proxies}

        elif type(proxies) == dict:
            self.proxies = {p: {"ignore_urls": proxies[p]['ignore_urls'] if "ignore_urls" in proxies[p] else [], 
                                "concurent_requests": proxies[p]['concurent_requests'] if "concurent_requests" in proxies[p] else 0} 
                            for p in proxies}

        else:
            raise Exception("_InterfaceProxy.__init__: proxies type error")

TypeUrls = Dict[str, Dict[str, List[str] | int]]
class _InterfaceUrls:
    urls: TypeUrls

    def __init__(self, urls):
        if type(urls) == str:
            with open(urls) as file:
                try:
                    urls = json.load(file)
                except:
                    urls = file.read()
                    urls = urls.split("\n")

        if type(urls) == list:
            self.urls = {p: {"ignore_proxies": [], "maxReqsPerNSec": 6, "NSec": 2, "headers":{}} for p in urls}

        elif type(urls) == dict:
            self.urls = {p: {
                "ignore_proxies": urls[p]['ignore_proxies'] if "ignore_proxies" in urls[p] else [], 
                 "maxReqsPerNSec": urls[p]['maxReqsPerNSec'] if "maxReqsPerNSec" in urls[p] else 6,
                 "NSec": urls[p]['NSec'] if "NSec" in urls[p] else 2,
                 "headers": urls[p]['headers'] if "headers" in urls[p] else {}
                            } for p in urls}

        else:
            raise Exception("_InterfaceUrls.__init__: urls type error")

class _InterfacePollingSettings:
    
    map_one_request: int
    sleep_between_iterations: float
    func_make_request: Callable[..., ClientResponse]
    func_find_error: Callable[..., Any]
    func_process_responce: Callable[..., Any]
    headers: dict
    errors_max_per_N_s: int
    errors_N_s: float
    timeout: float
    
    

    def __init__(self, 
                 map_one_request: int, 
                 tiers: list,
                 sleep_between_iterations: float, 
                 func_make_request: Callable[..., ClientResponse],
                 func_find_error: Callable[[ClientResponse, Payload], Any], 
                 func_process_failure: Callable[[Pair], Any], 
                 func_process_responce: Callable[..., Any],
                 headers: dict,
                 errors_max_per_N_s: int,
                 errors_N_s: float,
                 timeout: float,
                 tasks_one_time: bool
                ):
        self.tasks_one_time = tasks_one_time
        self.tiers = tiers
        self.map_one_request = map_one_request
        self.sleep_between_iterations = sleep_between_iterations
        self.func_make_request = func_make_request
        self.func_find_error = func_find_error
        self.func_process_failure = func_process_failure
        self.func_process_responce = func_process_responce
        self.headers = headers
        self.errors_max_per_N_s = errors_max_per_N_s
        self.errors_N_s = errors_N_s
        self.timeout = timeout
