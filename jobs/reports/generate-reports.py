""" Script for generating HTML output
"""

import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
from pathlib import Path
from collections import OrderedDict
from boto3.dynamodb.conditions import Key, Attr
import boto3
import click
import os
import sh
import yaml
from staticjinja import Site

session = boto3.Session(region_name='us-east-1')
s3 = session.resource('s3')
dynamodb = session.resource('dynamodb')
bucket = s3.Bucket('jenkaas')

OBJECTS = bucket.objects.all()

def upload_html():
    sh.aws.s3.sync('reports/_build', 's3://jenkaas')

def download_file(key, filename):
    """ Downloads file
    """
    s3.meta.client.download_file(bucket.name, key, filename)

def _parent_dirs():
    """ Returns list of paths
    """
    items = set()
    for obj in OBJECTS:
        if obj.key != 'index.html':
            items.add(obj.key)
    return list(sorted(items))

def _gen_days(numdays=30):
    """ Generates last numdays, date range
    """
    base = datetime.today()
    date_list = [(base - timedelta(
        days=x)).strftime('%Y-%m-%d') for x in range(0, numdays)]
    return date_list

def _gen_metadata():
    """ Generates metadata
    """
    click.echo("Generating metadata...")
    items = []
    table = dynamodb.Table('CIBuilds')

    # Required because only 1MB are returned
    # See: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GettingStarted.Python.04.html
    response = table.scan()
    for item in response['Items']:
        items.append(item)
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        for item in response['Items']:
            items.append(item)
    metadata = OrderedDict()
    db = OrderedDict()
    for obj in items:
        if obj['job_name'] not in db:
            db[obj['job_name']] = {}

        if 'build_endtime' not in obj:
            continue

        if 'test_result' not in obj:
            result_bg_class = 'bg-light'
        elif not obj['test_result']:
            result_bg_class = 'bg-danger'
        else:
            result_bg_class = 'bg-success'

        obj['bg_class'] = result_bg_class

        try:
            day = datetime.strptime(obj['build_endtime'],
                                    '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d')
        except:
            day = datetime.strptime(obj['build_endtime'],
                                    '%Y-%m-%d %H:%M:%S.%f').strftime('%Y-%m-%d')

        if day not in db[obj['job_name']]:
            db[obj['job_name']][day] = []
        db[obj['job_name']][day].append(obj)
    return db

def _gen_rows():
    """ Generates reports
    """
    days = _gen_days()
    metadata = _gen_metadata()
    rows = []
    for jobname, jobdays in sorted(metadata.items()):
        sub_item = [jobname]
        for day in days:
            if day in jobdays:
                max_build_number = max(
                    int(item['build_number']) for item in jobdays[day])
                for job in jobdays[day]:
                    if job['build_number'] == str(max_build_number):
                        sub_item.append(job)
            else:
                sub_item.append(
                    {'job_name': jobname,
                     'bg_class': ''})
        rows.append(sub_item)
    return rows


@click.group()
def cli():
    pass

@cli.command()
def list():
    """ List keys in dynamodb
    """
    table = dynamodb.Table('CIBuilds')
    response = table.scan()
    click.echo(response['Items'])


@cli.command()
def build():
    """ Generate a report
    """
    ci_results_context = {
        'rows': _gen_rows(),
        'headers': [datetime.strptime(day, '%Y-%m-%d').strftime('%m-%d')
                    for day in _gen_days()],
        'modified': datetime.now()
    }

    site = Site.make_site(
        contexts=[
            ('index.html', ci_results_context),
        ],
        outpath='reports/_build')
    site.render()
    upload_html()

if __name__ == "__main__":
    cli()
