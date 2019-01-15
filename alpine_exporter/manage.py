import click
from app import app
from jobs import upload_fresh_data


@app.cli.command()
@click.argument('exam_id')
def upload(exam_id):
    upload_fresh_data.delay(exam_id)
