import asyncio
import aiohttp
import json
import math
import os
import time
import hashlib
import uuid

from choirless_lib import mqtt_status, create_cos_client

@mqtt_status()
def main(args):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        async_main(args)
    )

async def async_main(args):
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    definition_key = args.get('key', notification.get('object_name', ''))

    definition_bucket = args['definition_bucket']

    ## First part, check we have all we need to do the composition
    ## if not exit. This is intended to be fast as will get called
    ## often

    # Download the definition file for this job
    definition_object = cos.get_object(
        Bucket=definition_bucket,
        Key=definition_key,
    )
    definition = json.load(definition_object['Body'])
    
    choir_id = definition['choir_id']
    song_id = definition['song_id']

    output_spec = definition['output']
    input_specs = definition['inputs']

    # Calculate number of rows
    rows = set()
    for spec in input_specs:
        x, y = spec['position']
        rows.add(y)
    rows = sorted(rows)
    num_rows = len(rows)
    rows_hash = calc_hash_rows(rows)
    run_id = str(uuid.uuid4())[:8]
    
    print("We are the main process")
    headers = {'X-Require-Whisk-Auth': args['auth']}
    t1 = time.time()
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for row in rows:
            tasks.append(call_child(session, args, run_id, row, rows_hash, 'combined'))
#            tasks.append(call_child(session, args, run_id, row, rows_hash, 'audio'))
#            tasks.append(call_child(session, args, run_id, row, rows_hash, 'video'))
            
        await asyncio.gather(*tasks)
    t2 = time.time()

    ret = {'status': 'spawned children',
           'run_id': run_id,
           'definition_key': definition_key,
           'time': int(t2-t1)}

    return ret

async def call_child(client, args, run_id, row, rows_hash, compositor):
    notification = args.get('notification', {})
    definition_key = args.get('key', notification.get('object_name', ''))
    data = {'row_num': row,
            'run_id': run_id,
            'rows_hash': rows_hash,
            'compositor': compositor,
            'key': definition_key,
            'definition_key': definition_key}

    # Construct the url of the scaler process
    __OW_API_HOST = os.environ['__OW_API_HOST']
    __OW_NAMESPACE = os.environ['__OW_NAMESPACE']
    url = f"{__OW_API_HOST}/api/v1/web/{__OW_NAMESPACE}/choirless/renderer_compositor_child.json"
        
    print(f"Calling {compositor} child: row {row} url {url}")
    resp = await client.post(
        url=url,
        json=data,
        raise_for_status=True)

def calc_hash_rows(rows):
    val = '-'.join([ str(x) for x in sorted(rows) ])
    hash = hashlib.sha1(val.encode('utf-8')).hexdigest()
    return hash[:8]
    
