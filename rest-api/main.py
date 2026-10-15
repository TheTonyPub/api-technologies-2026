from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
from typing import Optional

items: dict[int, dict] = {}
current_id = 1

app = FastAPI()

class LoginData(BaseModel):
    UserName: str = Field(..., min_length=3, max_length=50)

class UpdateData(BaseModel):
    UserName: str = Field(..., min_length=3, max_length=50)

class MessageResponse(BaseModel):
    message: str

@app.get("/items", response_model=MessageResponse)
async def get_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": f"Item {item_id}"}

@app.post("/items", response_model=MessageResponse)
async def create_item(data: LoginData):
    global current_id
    items[current_id] = {"id": current_id, "user_name": data.user_name}
    item_id = current_id
    current_id += 1
    return {"message": f"Created item {item_id} with name {data.user_name}"}

@app.put("/items/{item_id}", response_model=MessageResponse)
async def update_item(item_id: int, data: UpdateData):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    
    items[item_id]["user_name"] = data.user_name
    return {"message": f"Item {item_id} updated to {data.user_name}"}


@app.delete("/items/{item_id}", response_model=MessageResponse)
async def delete_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    
    del items[item_id]
    return {"message": f"Item {item_id} deleted"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
