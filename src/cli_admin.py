import asyncio, typer
from database_wrapper import DBWrapper
from paths import PathWrap
app = typer.Typer()

@app.command("approve")
def approve(username: str):
    async def _run():
        CurrentPaths = PathWrap()
        CurrentPaths.validate_all_paths()
        db = DBWrapper(CurrentPaths.db_file)
        await db.init_db()
        async with db.get_connection() as conn:
            await conn.execute(
                "UPDATE users SET approved=1 WHERE username=?", (username,)
            )
            await conn.commit()
        typer.echo(f"✔ User {username} approved")

    asyncio.run(_run())

@app.command("list_users")
def list_users():
    async def run():
        CurrentPaths = PathWrap()
        CurrentPaths.validate_all_paths()
        db = DBWrapper(CurrentPaths.db_file)
        await db.init_db()
        async with db.get_connection() as conn:
            async with conn.execute("SELECT username, approved FROM users") as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    typer.echo(f"User: {row[0]}, Approved: {row[1]}")

    asyncio.run(run())


if __name__ == "__main__":
    app()
