import json
import os
import time
from pathlib import Path
import uuid

import paho.mqtt.publish as publish


def safe_publish(topic, msg, broker, timeout=5):
    if not broker:
        print("No MQTT broker configured")
    else:
        try:
            hostname, port = broker.split(':')
            return publish.single(topic,
                                  json.dumps(msg),
                                  hostname=hostname,
                                  port=int(port),
                                  keepalive=timeout)
        except Exception as e:
            print("Could not send MQTT message:", e)
    

def mqtt_status(helper=None):
    helper_ = helper
    
    def wrap(method):
        
        def wrapped_f(args):

            # Get the broker to use
            mqtt_broker = args.get('mqtt_broker')
            
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
                   'status_id': str(uuid.uuid4())
            }
            
            if stage in ['convert_format', 'calculate_alignment', 'trim_clip']:
                msg['part_id'] = key_parts[2]

            t1 = time.time()
            msg['event'] = 'start'
            msg['start'] = int(t1)

            if helper_ is not None:
                msg.update(helper_(args))
            
            safe_publish(
                f"choirless/{choir_id}/{song_id}/renderer/{stage}",
                msg,
                mqtt_broker
            )

            try:
                result = method(args)
                t2 = time.time()

                msg['event'] = 'end'
                msg['end'] = int(t2)
                msg['duration'] = int(t2-t1)
                
                safe_publish(
                    f"choirless/{choir_id}/{song_id}/renderer/{stage}",
                    msg,
                    mqtt_broker,
                )

            except Exception as e:
                t2 = time.time()
                msg['event'] = 'error'
                msg['error'] = str(e)       
                msg['end'] = int(t2)
                msg['duration'] = int(t2-t1)

                safe_publish(
                    f"choirless/{choir_id}/{song_id}/renderer/{stage}",
                    msg,
                    mqtt_broker,
                )
                raise
            
            return result

        return wrapped_f
    
    return wrap
