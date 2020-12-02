import numpy as np
import librosa
from surfboard.sound import Waveform
import optuna
from pathlib import Path
from collections import defaultdict
from itertools import permutations, product
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

            features = {'s': s,
                        'sr': sr,
                        'offset': int(offset),
                        'filename': str(filename.name),
            }
        
            data[f'{choir_id}+{song_id}'].append(features)

    valid_combos = []
    for song_parts in data.values():
        for a, b in permutations(song_parts, 2):
            if a['offset'] == 0:
                valid_combos.append([a, b, b['offset']])

    starts = [0]
    lengths = [30, 60, 120, 180]
                
    print("Number of parts:", len(valid_combos))
    print("Starts:", starts)
    print("Lengths:", lengths)
    print("Total number of tests: ", len(valid_combos)*len(starts)*len(lengths))
    ob = partial(objective, valid_combos, starts, lengths, False)

    study = optuna.load_study(study_name='distributed-example', storage='sqlite:///example.db')

    # Start with the existing params as these may still be valid
    study.enqueue_trial(EXISTING_PARAMS)

    study.optimize(ob,
                   n_trials=100,
                   n_jobs=1)

    print(study.best_params)

    objective(valid_combos, starts, lengths, True, study.best_trial)

                
def objective(valid_combos, starts, lengths, debug, trial):
    chroma_weight = trial.suggest_discrete_uniform('chroma_weight', 0.0, 1.0, 0.1)
    sf_weight = trial.suggest_discrete_uniform('sf_weight', 0.0, 1.0, 0.1)
    cf_weight = trial.suggest_discrete_uniform('cf_weight', 0.0, 1.0, 0.1)
    
    num_synced = 0
    num_parts = len(valid_combos)
    num_starts = len(starts) * len(lengths)
    total_tests = num_parts * num_starts

    if debug:
        fig = plt.figure(figsize=(8*num_starts, 4*num_parts))
    
    for i, (a, b, actual_offset) in enumerate(valid_combos):

        for j, (start, length) in enumerate(product(starts, lengths)):

            if debug:
                ax = fig.add_subplot(num_parts, num_starts, (i * num_starts) + j + 1)
                ax.set_title(b['filename'])
            else:
                ax = None

            offset = calc_offset(a['s'], a['sr'], b['s'], b['sr'],
                                 ax=ax,
                                 start_seconds=start,
                                 length_seconds=length,
                                 chroma_weight=chroma_weight,
                                 sf_weight=sf_weight,
                                 cf_weight=cf_weight,
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
                if num_synced == total_tests:
                    trial.study.stop()

    if debug:
        fig.savefig('tune_sync.png', bbox_inches='tight')
                
    return num_synced
        
    

if __name__ == '__main__':

    main()
