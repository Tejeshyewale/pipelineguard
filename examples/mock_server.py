import asyncio
import websockets
import json

# Global failure counter for the mock server to trigger a failover
request_count = 0

async def handler(websocket):
    global request_count
    async for message in websocket:
        try:
            req = json.loads(message)
            seq = req.get("seq", 1)
            command = req.get("command", "")
            
            success = True
            body = {}
            
            if command == "use":
                body = {"token": "tok-dummy"}
            elif command == "rrext_process" or command == "send":
                request_count += 1
                if request_count == 1:
                    # Fail the first request to trigger failover
                    success = False
                    body = {"message": "Simulated failure for demo"}
                else:
                    body = {"name": "response", "data": {"answer": "mock answer"}}
            elif command == "get_task_status":
                body = {"state": "completed", "exitCode": 0}
                
            resp = {
                "type": "response",
                "request_seq": seq,
                "success": success,
                "command": command,
                "body": body
            }
            if not success:
                resp["message"] = body.get("message", "Error")
            await websocket.send(json.dumps(resp))
        except Exception:
            pass

async def main():
    print("Starting mock RocketRide server on port 5565...")
    async with websockets.serve(handler, "0.0.0.0", 5565):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
