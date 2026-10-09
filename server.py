import uvicorn

PORT = 8000

if __name__ == "__main__":
    print(f"Serving dashboard and API at http://localhost:{PORT}")
    uvicorn.run("api_server:app", host="127.0.0.1", port=PORT)
