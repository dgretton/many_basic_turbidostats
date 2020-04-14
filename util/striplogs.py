import datetime as dt
from matplotlib import pyplot as plt
import os

with open(os.path.join('..', 'method_local', 'log', 'main.log')) as f:
    lines = [l for l in f]
def plot_lists(token):
    split_token = ' root INFO ' + token + ' '
    contiguous_blocks = [[]]

    last_time = start_time = None
    for line in lines:
        if split_token in line:
            time_str, data = line.split(split_token)
            time = dt.datetime.strptime(time_str, '[%Y-%m-%d %H:%M:%S,%f]')
            #if last_time:
            #    print((time - last_time).seconds)
            if last_time and (time - last_time).seconds > 30*60:
                contiguous_blocks.append([])
            current_block = contiguous_blocks[-1]
            #print(current_block)
            if not current_block:
                print(len(current_block))
                start_time = time
            delta_time = time - start_time
            current_block.append((delta_time.seconds/3600+delta_time.days*24, eval(data)))
            last_time = time

    #print(contiguous_blocks[-1])
    #print(len(contiguous_blocks))
    #print(time)
    #print(start_time)
    plt.figure(token)
    plt.plot(*zip(*contiguous_blocks[-1]))
    with open(token + '.csv', 'w+') as csv:
        for line in contiguous_blocks[-1]:
            csv.write(','.join((str(w) for w in line)).replace(']', '').replace('[', '') + '\n')
    plt.savefig(token + '.pdf')


for token in 'OD ESTIMATES', 'K ESTIMATES', 'REPLACEMENT VOLUMES':
    plot_lists(token)
    
plt.show()
