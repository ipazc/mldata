#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import concurrent
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading
from time import sleep
from pyzip import PyZip

__author__ = 'Iván de Paz Centeno'

pool = ThreadPoolExecutor(4)
UPDATE_INTERVAL = 2 #seconds

class AsyncSmartUpdater(object):

    def __init__(self, server_info, api_wrapper_owner):
        self.server_info = server_info
        self.api_wrapper_owner = api_wrapper_owner
        self.content_put_queue = Queue()
        self.element_update_queue = Queue()
        self.queues_priorities = [self.element_update_queue, self.content_put_queue]
        self.__exit = False
        self.__cancel_pending_jobs = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._thread_func, daemon=True)
        self.thread.start()

    @property
    def _exit(self):
        with self.lock:
            exit_value = self.__exit
        return exit_value

    @_exit.setter
    def _exit(self, do_exit=True):
        with self.lock:
            self.__exit = do_exit

    @property
    def _cancel_pending_jobs(self):
        with self.lock:
            cancel_pending_jobs = self.__cancel_pending_jobs
        return cancel_pending_jobs

    @_cancel_pending_jobs.setter
    def _cancel_pending_jobs(self, do__cancel_pending_jobs=True):
        with self.lock:
            self.__cancel_pending_jobs = do__cancel_pending_jobs

    def __queue_with_higher_priority_waiting(self, queue):
        """
        Checks if is there any queue with higher priority waiting than the speicified queue.
        :param queue: queue to check from
        :return: boolean True if there is at least one queue with higher priority waiting. False otherwise.
        """
        index = 0
        current_queue_index = self.queues_priorities.index(queue)

        while index < current_queue_index and self.queues_priorities[index].qsize() == 0:
            index += 1

        return index != len(self.queues_priorities) and index < current_queue_index

    def __any_queue_with_elements(self):
        return any([queue.qsize() > 0 for queue in self.queues_priorities])

    def _thread_func(self):
        ps = self.server_info['Page-Size']
        queue_types = {self.content_put_queue:'binary', self.element_update_queue: 'json'}

        while not self._exit or (not self._cancel_pending_jobs and self.__any_queue_with_elements()):
            print("I'm here... {} {} {}".format(self._exit, self._cancel_pending_jobs, self.__any_queue_with_elements()))
            # Let's gather all the updates from the queue to serialize them
            sleep(UPDATE_INTERVAL)

            for queue in self.queues_priorities:

                if self.__queue_with_higher_priority_waiting(queue):
                    print("HERE???")
                    break # This forces the loop to start running through the most priority queues again.

                gathered_elements = []

                futures = []
                while queue.qsize() > 0:

                    # Check that queues with highest priority are not
                    if self.__queue_with_higher_priority_waiting(queue):
                        break # This forces the loop to start running through the most priority queues again.

                    gathered_elements.append(queue.get())

                    # This is the smart action: we combine several requests into one
                    if len(gathered_elements) > ps:
                        futures.append(pool.submit(self.__do_update, queue_types[queue], gathered_elements))
                        gathered_elements = []

                if len(gathered_elements) > 0:
                    futures.append(pool.submit(self.__do_update, queue_types[queue], gathered_elements))

                concurrent.futures.wait(futures)

    def __do_update(self, request_kind, elements):

        if len(elements) > 0:
            url = elements[0][0]
        else:
            url = None

        kwargs_list = {}
        for element in elements:
            kwargs_list[element[1]] = element[2]

        if len(kwargs_list) == 0:
            return None

        if request_kind == "json":
            self.api_wrapper_owner._patch_json(url, extra_data=None, json_data={'elements': kwargs_list})
        else: # request_kind == "binary":
            self.api_wrapper_owner._put_binary(url, extra_data=None, binary=PyZip(kwargs_list).to_bytes())

        return True

    def queue_update(self, url, element_id, kwargs):
        self.element_update_queue.put([url, element_id, kwargs])

    def queue_content_update(self, url, element_id, content):
        self.content_put_queue.put([url, element_id, content])

    def stop(self, cancel_pending_jobs=False):
        self.__exit = True
        self.__cancel_pending_jobs = cancel_pending_jobs
        self.thread.join(10)