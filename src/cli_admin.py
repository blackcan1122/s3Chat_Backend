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

@app.command("add_col")
def add_col(colname : str, datatype : str):
    allowed_list = ["TEXT",
                    "INTEGER",
                    "REAL",
                    "BOOLEAN",
                    "DATETIME"]
    async def run():
        if datatype not in allowed_list:
            typer.echo(f"{datatype} is not a valid SQL Datatype")
            return
        CurrentPaths = PathWrap()
        db = DBWrapper(CurrentPaths.db_file)
        await db.init_db()
        async with db.get_connection() as conn:
            await conn.execute(f"ALTER TABLE users ADD COLUMN {colname} {datatype}")
            await conn.commit()
        typer.echo(f"Added {colname} in Table 'users' with the Datatype {datatype}")
    asyncio.run(run())

@app.command("give_admin")
def give_admin(username : str):
    async def run():
        CurrentPaths = PathWrap()
        db = DBWrapper(CurrentPaths.db_file)
        await db.init_db()
        async with db.get_connection() as conn:
            async with conn.execute("PRAGMA table_info(users)") as cursor:
                columns = await cursor.fetchall()
                admin_exists = any(col[1] == 'admin' for col in columns)
            
            if not admin_exists:
                typer.echo("Admin column does not exist. Please add it first using add_col command.")
                return
            
            # Check if user exists
            async with conn.execute("SELECT username FROM users WHERE username=?", (username,)) as cursor:
                user = await cursor.fetchone()
                if not user:
                    typer.echo(f"User {username} not found.")
                    return
            
            # Set admin to true
            await conn.execute("UPDATE users SET admin=1 WHERE username=?", (username,))
            await conn.commit()

    typer.echo(f"✔ User {username} granted admin privileges")
    asyncio.run(run())
    


if __name__ == "__main__":
    app()
