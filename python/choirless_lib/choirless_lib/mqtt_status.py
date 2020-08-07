## Signed URL support
import json
import os
import time
from pathlib import Path

import paho.mqtt.publish as publish

def mqtt_status(helper=None):
    helper_ = helper
    
    def wrap(method):
        
        def wrapped_f(args):

            # Get the stage from the current env
            stage = os.environ.get('__OW_ACTION_NAME')
            try:
                stage = stage.split('/')[-1]
            except IndexError:
                stage = 'unknown'

            notification = args.get('notification', {})
            key = args.get('key', notification.get('object_name', ''))

            key_parts = Path(key).stem.split('+')
            choir_id, song_id = key_parts[:2]
            
            msg = {'choir_id': choir_id,
                   'song_id': song_id,
                   'stage': stage,
            }
            
            if stage in ['convert_format', 'calculate_alignment', 'trim_clip']:
                msg['part_id'] = key_parts[2]
        
            mqtt_server, mqtt_port = args['mqtt_broker'].split(':')

            t1 = time.time()
            msg['event'] = 'start'
            msg['start'] = int(t1)

            if helper_ is not None:
                msg.extend(helper_(args))
            
            publish.single(
                f"choirless/{choir_id}/{song_id}/renderer/{stage}",
                json.dumps(msg),
                hostname=mqtt_server,
                port=int(mqtt_port)
            )
            
            result = method(args)
            t2 = time.time()

            msg['event'] = 'end'
            msg['end'] = int(t2)
            msg['duration'] = int(t2-t1)
            
            publish.single(
                f"choirless/{choir_id}/{song_id}/renderer/{stage}",
                json.dumps(msg),
                hostname=mqtt_server,
                port=int(mqtt_port)
            )
            
            return result

        return wrapped_f
    
    return wrap
