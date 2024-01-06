import asyncio
from typing import Union, List, Dict, Any

from typings import (
    TaskOutput,
    AgentOutput,
    ChatHistoryItem,
    SampleIndex,
    TaskSampleExecutionResult,
)


class SessionController:
    def __init__(self):
        # initiating a sessstion controller
        # what does the session controller do? is it the same as th eask controller
        self.agent_lock = asyncio.Lock() # locking the agent for single task use, i.e the agetn can only be acessed by one worker at a time no matter how many workers are running concurretly
        self.env_lock = asyncio.Lock() # locking the environment for single task use, i.e it can only be accessed by one worker even if multiple workers were running concurrently
        self.agent_signal = asyncio.Semaphore(0) # semaphores are used to contorl access to limitied resources, like locks but they count down after every coroutine that requests them
        self.env_signal = asyncio.Semaphore(0) # setting an environment and agent semaphor
        self.env_input: Union[None, AgentOutput] = None # the environment input is the agent output
        # the input to the environmet is the output of the agent, so what is the input of the agent
        '''
        class AgentOutput(BaseModel):
            status: AgentOutputStatus = AgentOutputStatus.NORMAL
            content: Union[str, None] = None

            # at least one of them should be not None
            @root_validator(pre=False, skip_on_failure=True)
            def post_validate(cls, instance: dict):
                assert (
                    instance.get("status") is not AgentOutputStatus.NORMAL
                    or instance.get("content") is not None
                ), "If status is NORMAL, content should not be None" 
                return instance
        '''
        
        self.env_output = TaskOutput()
        '''
        class TaskOutput(BaseModel):
            index: Union[None, SampleIndex] = None
            status: SampleStatus = SampleStatus.RUNNING
            result: JSONSerializable = None
            history: Union[None, List[ChatHistoryItem]] = None
        '''

    async def agent_pull(
        self, env_input: Union[AgentOutput, None] = None
    ) -> TaskOutput:
        # what does the agent pull do?
        async with self.agent_lock:
            if env_input is not None:
                self.env_input = env_input
                self.env_signal.release()
            print("acquiring agent signal")
            await self.agent_signal.acquire()
            print("pos 5")
            return self.env_output

    async def env_pull(self, history: List[ChatHistoryItem]) -> AgentOutput:
        print(">> env pull waiting")
        # what is going on here?
        async with self.env_lock:
            self.env_output.history = history
            self.agent_signal.release()
            await self.env_signal.acquire()
            return self.env_input

    async def env_finish(self, result: TaskOutput = None) -> None:
        print(">> env finish waiting")
        async with self.env_lock:
            print(">> env finish done")
            history = self.env_output.history
            self.env_output = result
            if self.env_output.history is None:
                self.env_output.history = history
            self.agent_signal.release()

    def get_status(self):
        waiting_for_env = self.agent_lock.locked()
        waiting_for_agent = self.env_lock.locked()
        return {
            "waiting_for_env": waiting_for_env,
            "waiting_for_agent": waiting_for_agent,
            "env_input": self.env_input,
            "env_output": self.env_output.dict(),
        }


class Session:
    def __init__(self) -> None:
        self.history: List[ChatHistoryItem] = []
        self.controller = SessionController()

    def inject(self, item):
        if not item:
            return
        if isinstance(item, ChatHistoryItem):
            self.history.append(item)
        elif isinstance(item, Dict):
            self.history.append(ChatHistoryItem.parse_obj(item))
        elif isinstance(item, List):
            for sub_item in item:
                self.inject(sub_item)
        else:
            raise TypeError("Unsupported type %s" % type(item))

    def clear(self):
        self.history = []

    @staticmethod
    def _calc_segments(msg: str):
        segments = 0
        current_segment = ""
        inside_word = False

        for char in msg:
            if char.isalpha():
                current_segment += char
                if not inside_word:
                    inside_word = True
                if len(current_segment) >= 7:
                    segments += 1
                    current_segment = ""
                    inside_word = False
            else:
                if inside_word:
                    segments += 1
                    current_segment = ""
                    inside_word = False
                if char not in [" ", "\n"]:
                    segments += 1

        if len(current_segment) > 0:
            segments += 1

        return segments

    def filter_messages(self, messages: List[ChatHistoryItem]) -> List[ChatHistoryItem]:
        assert len(messages) % 2 == 1, "Invalid message length"

        threshold_segments = 3500
        return_messages: List[ChatHistoryItem] = []
        # only include the latest {threshold_segments} segments

        segments = self._calc_segments(messages[0].content)

        for message in messages[:0:-1]:
            segments += self._calc_segments(message.content)
            if segments >= threshold_segments:
                break
            return_messages.append(message)

        if len(return_messages) > 0 and return_messages[-1].role == "user":
            return_messages.pop()

        instruction = messages[0].content

        omit = len(messages) - len(return_messages) - 1

        if omit > 0:
            instruction += f"\n\n[NOTICE] {omit} messages are omitted."
            print(f"Warning: {omit} messages are omitted.")

        return_messages.append(ChatHistoryItem(role="user", content=instruction))

        return_messages.reverse()
        return return_messages

    async def action(self, *injection) -> AgentOutput:
        print("session.action")
        self.inject(list(injection))
        print("pulling env")
        agent_response = await self.controller.env_pull(
            self.filter_messages(self.history)
        )
        self.history.append(
            ChatHistoryItem(
                role="agent", content=agent_response.content or agent_response.status
            )
        )
        return agent_response


class Task:
    def __init__(self, name: str, concurrency: int = 1, *args, **kwargs):
        self.name = name
        self.concurrency = concurrency

    def get_indices(self) -> List[SampleIndex]:
        raise NotImplementedError()

    async def start_sample(
        self, index: SampleIndex, session: Session
    ) -> TaskSampleExecutionResult:
        raise NotImplementedError()

    def calculate_overall(self, results: List[TaskOutput]) -> Dict[str, Any]:
        raise NotImplementedError()

    def release(self):
        pass


class VirtualTask(Task):
    # whats the difference between a task and a virtual task?
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(name="virtual-task", *args, **kwargs)

    def get_indices(self) -> List[Any]:
        return list(range(10))

    async def start_sample(self, index, session: Session):
        print("task start sample")
        for loop_times in range(3):
            await asyncio.sleep(1)
            res = await session.action(
                {"role": "user", "content": "Loop: %d" % loop_times}
            )
            print("TASK", res)
        return {"succeed": True, "round": 10}

    def calculate_overall(self, results: List[TaskOutput]) -> Dict[str, Any]:
        return {"score": 0.4}
