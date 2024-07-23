from fastapi import FastAPI

app = FastAPI()

items = { "foo" : "The Foo Wrestless" }

@app.get("/items/{item_id}")
async def read_item(item_id: str):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item": items[item_id]}

@app.get("/")
def read_root():
    return {"Hello": "World"}
