
import typer


app = typer.Typer(pretty_exceptions_show_locals=False)

from quality_checker.quality_checker import app as quality_app
app.registered_commands = quality_app.registered_commands


if __name__ == "__main__":
    app()
