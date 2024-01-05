import asyncio
from time import sleep

async def testing():
    # ayncrhronous python programming for the masses
    print("hello")
    await asyncio.sleep(3)
    print("my name is ")
    await asyncio.sleep(3)
    print("Kosi")
    
    
async def mycustomeeventloop():
    # needs to be running withing an event loop
    task1 = asyncio.create_task(testing())
    task2 = asyncio.create_task(testing())
    
    # can only await in an async function
    await asyncio.gather(task1, task2)
    
asyncio.run(mycustomeeventloop())