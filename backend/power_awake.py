"""Keep Windows awake only while this server has active background jobs."""
import asyncio
import ctypes
import logging
import os
from . import store

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def set_execution_state(flags):
    function = ctypes.windll.kernel32.SetThreadExecutionState
    function.argtypes = [ctypes.c_uint]
    function.restype = ctypes.c_uint
    return function(flags)


async def maintain(interval=0.5):
    if os.name != 'nt':
        return
    held = False
    failure_logged = False
    try:
        while True:
            active = store.active_job_count() > 0
            if active != held:
                flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if active else 0)
                if set_execution_state(flags):
                    held = active
                    failure_logged = False
                elif not failure_logged:
                    logging.warning('Windows rejected the workbench sleep-prevention request')
                    failure_logged = True
            await asyncio.sleep(interval)
    finally:
        if held and not set_execution_state(ES_CONTINUOUS):
            logging.warning('Windows rejected the workbench sleep-prevention release')
