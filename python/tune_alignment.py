import numpy as np
import librosa
from surfboard.sound import Waveform
import optuna
from pathlib import Path
from collections import defaultdict
from itertools import permutations
from functools import partial

from calculate_alignment import calc_offset, SAMPLE_RATE

def main():

    data = defaultdict(list)
    print("Loading audio files")
    for filename in Path('tune_data').glob('*.wav'):
        print(filename.name)
        choir_id, song_id, _, offset = filename.stem.split('+')
        s, sr = librosa.load(str(filename),
                             sr=SAMPLE_RATE,
                             mono=True,
                             offset=0,
                             duration=180)
        sound0 = Waveform(signal=s, sample_rate=sr)
        sf = sound0.spectral_flux()[0]
        cf = sound0.crest_factor()[0]

        features = {'s': s,
                    'sf': sf,
                    'cf': cf,
                    'offset': int(offset),
        }
        
        data[f'{choir_id}+{song_id}'].append(features)

    valid_combos = []
    for song_parts in data.values():
        for a, b in permutations(song_parts, 2):
#            if a['offset'] < b['offset']:
            if a['offset'] == 0:
                valid_combos.append([a, b, b['offset'] - a['offset']])


    ob = partial(objective, valid_combos, False)
                
    study = optuna.create_study(pruner=optuna.pruners.MedianPruner())
#    study = optuna.create_study(pruner=optuna.pruners.ThresholdPruner(upper=1.0))
    study.optimize(ob,
                   n_trials=100,
                   n_jobs=1)

    print(study.best_params)

    objective(valid_combos, True, study.best_trial)

                
def objective(valid_combos, debug, trial):
    bandwidth = trial.suggest_int('bandwidth', 1, 5)
    q = trial.suggest_discrete_uniform('q', 0.1, 1.0, 0.05)
    decay = trial.suggest_discrete_uniform('decay', 0.1, 1.0, 0.05)
    num_res = trial.suggest_int('num_res', 1, 46, 5)
    base_score= trial.suggest_discrete_uniform('base_score', 0.0, 1.0, 0.05)

    errors = []
    for i, (a, b, actual_offset) in enumerate(valid_combos):
        features = {'sf0': a['sf'],
                    'cf0': a['cf'],
                    'sf1': b['sf'],
                    'cf1': b['cf'],
                    }
        offset = calc_offset(features,
                             debug=False,
                             q=q,
                             decay=decay,
                             num_res=num_res,
                             bandwidth=bandwidth,
                             base_score=base_score
        )

        if debug:
            print(a['offset'], b['offset'], actual_offset, offset)
        
        errors.append((actual_offset - offset) / actual_offset)
        intermediate_mse = np.mean(np.array(errors) ** 2)
        trial.report(intermediate_mse, i)

        # Handle pruning based on the intermediate value.
        if trial.should_prune():
            raise optuna.TrialPruned()

    errors = np.array(errors) ** 2
    mse = np.mean(errors)

    return mse
        
    

if __name__ == '__main__':

    main()
