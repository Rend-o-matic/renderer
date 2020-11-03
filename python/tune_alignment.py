import numpy as np
import librosa
from surfboard.sound import Waveform
import optuna
from pathlib import Path
from collections import defaultdict
from itertools import permutations
from functools import partial
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from calculate_alignment import calc_offset, SAMPLE_RATE, PARAMS as EXISTING_PARAMS

cache_dir = "/Users/matt/Downloads/choirless_videos"

def main():

    data = defaultdict(list)
    print("Loading audio files")
    for json_file in Path('tune_data').glob('*.json'):
        spec = json.load(json_file.open())
        print("Loading JSON file:", json_file.name)
        choir_id = spec['choir_id']
        song_id = spec['song_id']

        for part in spec['inputs']:
            part_id = part['part_id']
            offset = int(part['offset'])

            filename = Path(cache_dir, f'{choir_id}+{song_id}+{part_id}.nut')
            print("loading:", filename)

            s, sr = librosa.load(str(filename),
                                 sr=SAMPLE_RATE,
                                 mono=True,
                                 offset=0,
                                 duration=180)
            sound0 = Waveform(signal=s, sample_rate=sr)
            sf = sound0.spectral_flux()[0]
            cf = sound0.crest_factor()[0]
            chroma = np.argmax(sound0.chroma_cqt(), axis=0) / 12

            features = {'s': s,
                        'sf': sf,
                        'cf': cf,
                        'chroma': chroma,
                        'offset': int(offset),
                        'filename': str(filename.name),
            }
        
            data[f'{choir_id}+{song_id}'].append(features)

    valid_combos = []
    for song_parts in data.values():
        for a, b in permutations(song_parts, 2):
            if a['offset'] == 0:
                valid_combos.append([a, b, b['offset']])


    print("Total number of tests: ", len(valid_combos))
    ob = partial(objective, valid_combos, False)

    study = optuna.load_study(study_name='distributed-example', storage='sqlite:///example.db')

    # Start with the existing params as these may still be valid
    study.enqueue_trial(EXISTING_PARAMS)

    study.optimize(ob,
                   n_trials=50,
                   n_jobs=1)

    print(study.best_params)

    objective(valid_combos, True, study.best_trial)

                
def objective(valid_combos, debug, trial):
    q = trial.suggest_discrete_uniform('q', 0.8, 1.0, 0.01)
    decay = trial.suggest_discrete_uniform('decay', 0.5, 1.0, 0.05)
    chroma_weight = trial.suggest_discrete_uniform('chroma_weight', 0.0, 1.0, 0.1)
    sf_weight = trial.suggest_discrete_uniform('sf_weight', 0.0, 1.0, 0.1)
    cf_weight = trial.suggest_discrete_uniform('cf_weight', 0.0, 1.0, 0.1)
    
    num_synced = 0
    num_combos = len(valid_combos)

    if debug:
        fig = plt.figure(figsize=(10, 6*num_combos))
    
    for i, (a, b, actual_offset) in enumerate(valid_combos):
        features = {'sf0': a['sf'],
                    'cf0': a['cf'],
                    'chroma_s0': a['chroma'],
                    'sf1': b['sf'],
                    'cf1': b['cf'],
                    'chroma_s1': b['chroma'],
                    }

        if debug:
            ax = fig.add_subplot(num_combos, 1, i+1)
            ax.set_title(b['filename'])
        else:
            ax = None
            
        offset = calc_offset(features,
                             ax=ax,
                             q=q,
                             decay=decay,
                             chroma_weight=chroma_weight,
                             sf_weight=sf_weight,
                             cf_weight=cf_weight
        )

        diff = abs(actual_offset - offset)
        if debug:
            print(b['filename'], int(actual_offset), int(offset), int(diff))
        if ax:
            ax.axvline(x=int(actual_offset), color='g', linestyle='--')

        if diff <= 50:
            num_synced += 1
        else:
            if ax:
                ax.set_facecolor('#ffeeee')

        if not debug:
            if num_synced == len(valid_combos):
                trial.study.stop()

    if debug:
        fig.savefig('tune_sync.png', bbox_inches='tight')
                
    return num_synced
        
    

if __name__ == '__main__':

    main()
