import traceback
import sys
import json
import os
import gevent
import taskcluster

from mozillapulse.config import PulseConfiguration
from mozillapulse.consumers import GenericConsumer

#DEBUG statement: please remove before release
def debug_print(msg):
    print msg
    # running in heroku causes stdio to be buffered therefore we flush
    sys.stdout.flush()


#TODO: move these to args and env options
#TODO: add task-exception exchange
exchanges = ['exchange/taskcluster-queue/v1/task-pending','exchange/taskcluster-queue/v1/task-running']
queue = taskcluster.Queue()
#TODO: make perm coalescer service pulse creds
consumer_args = {
    'applabel': 'jwatkins@mozilla.com|pulse-test2',
    'topic': ['#','#'],
    'durable': True,
    'user': '',
    'password': ''
}

def get_env_args():
    pass
    #TODO: get env args

def parse_args():
    #TODO: parse args and return them as options
    pass

class TcPulseConsumer(GenericConsumer):
    def __init__(self, exchanges, **kwargs):
        super(TcPulseConsumer, self).__init__(
            PulseConfiguration(**kwargs), exchanges, **kwargs)

class TaskEventApp(object):

    # pendingTasks is a dict where all pending tasks and their task definitions are kept
    # Tasks are added or removed based on msgs from task-pending, task-running, and task-exception
    # {'taskid': task_definition}
    pendingTasks = {}

    listener = None

    def __init__(self):
        pass

    def run(self):
        #TODO: bind with better topic to limit queue
        self.listener = TcPulseConsumer(exchanges, callback=self._route_callback_handler, **consumer_args)
        while True:
            try:
                self.listener.listen()
            except KeyboardInterrupt:
                #TODO: delete_queue doesn't work. fix me
                #self.listener.delete_queue()
                sys.exit(1)
            except:
                traceback.print_exc()

    def _route_callback_handler(self, body, message):
        """
        Route call body and msg to proper callback handler
        """
        taskState = body['status']['state']
        taskId = body['status']['taskId']
        #DEBUG statement: please remove before release
        debug_print ("taskId: %s (%s)" % (taskId, taskState))
        #DEBUG statement: please remove before release
        #print json.dumps(body, sort_keys=True, indent=4)
        if taskState == 'pending':
            self._add_task_callback(body, message, taskId)
        elif taskState == 'running' or taskState == 'exception':
            self._remove_task_callback(body, message, taskId)
        else:
            #TODO: Handle unknown states; for now just ack the msg
            message.ack()
        #DEBUG statement: please remove before release
        debug_print ("PendingTasks: %s" % (len(self.pendingTasks)))



    def _add_task_callback(self, body, message, taskId):
        taskDef = self._retrieve_taskdef(taskId)
        #TODO: handle if task already exists
        self.pendingTasks[taskId] = taskDef
        message.ack()

    def _remove_task_callback(self, body, message, taskId):
        #TODO: make idempotent; handle KeyError
        try:
            del self.pendingTasks[taskId]
        except:
            pass
        finally:
            message.ack()

    def _retrieve_taskdef(self, taskId):
        #TODO: retry api call
        #TODO: ssl error; fix me. InsecurePlatformWarning: A true SSLContext object is not available. This prevents urllib3 from configuring SSL appropriately and may cause certain SSL connections to fail. For more information, see https://urllib3.readthedocs.org/en/latest/security.html#insecureplatformwarning.
        #DEBUG: api call disabled
        taskDef = "TaskDef goes here"
        #taskDef = queue.task(taskId)
        #TODO: validate response
        #DEBUG statement: please remove before release
        #print json.dumps(status, sort_keys=True, indent=4)
        return taskDef

    def _spawn_taskdef_worker(self, taskId):
        """
        Spawn an async worker thread to fetch taskdef and fill in pendingTasks value
        Once worker has taskdef, Coalescer object is applied to possible add taskId to
        a current 'defined commonality list' already indexed or to build a new list
        """
        pass

    def _spawn_listener_worker(self, taskId):
        """
        Spawn an async worker thread to listen to pulse exchanges and add keys to dict
        """
        pass

class CoalescerGeneric(object):
    """
    Generic Coalescer object contains logic to build lists of tasks based on defined commonality
    eg. ProvisionerId, WorkerType, TaskDef env
    These 'defined commonalities' will be the index key used to quickly retrieve lists via the wsgi REST api
    Multiple objects may be defined accommodate mulitple 'defined commonalities'
    """

    def __init__(self):
        pass


def logging():
    #TODO: Setup logging facility to be compatible with heroku
    pass

def main():
    #TODO: parse args
    #TODO: parse and load evn options
    #TODO: pass args and options
    app = TaskEventApp()
    app.run()

if __name__ == '__main__':
    main()
