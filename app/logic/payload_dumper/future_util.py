import sys
from concurrent.futures import ALL_COMPLETED, FIRST_COMPLETED, FIRST_EXCEPTION, wait


def wait_interruptible(fs, timeout=None, return_when=ALL_COMPLETED):
    # Keep behavior similar to upstream on Windows where Ctrl+C handling is flaky.
    if sys.platform == 'win32' and timeout is None:
        while True:
            dones, undones = wait(fs, timeout=.5, return_when=return_when)
            if len(dones) == 0:
                continue
            need_return = False
            if return_when == FIRST_COMPLETED:
                for t in dones:
                    if t.done():
                        need_return = True
                        break
            elif return_when == FIRST_EXCEPTION:
                for t in dones:
                    if t.exception(0) is not None:
                        need_return = True
                        break
            if len(undones) == 0:
                need_return = True
            if need_return:
                return dones, undones
    else:
        return wait(fs, timeout=timeout, return_when=return_when)
