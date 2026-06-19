from fastmcp import FastMCP

mcp = FastMCP("gymrat-mcp")

@mcp.tool()
def get_profile(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "goal": "muscle_gain",
        "experience": "beginner",
    }

if __name__ == "__main__":
    mcp.run()
