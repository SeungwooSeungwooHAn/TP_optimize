import numpy as np
from Network_V2 import *
import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'
import torch
import random
import matplotlib.pyplot as plt
device='cuda'
class Problem_sampling:
    def __init__(self,block_number,location_number,transporter_type,transporter_number,transporter_initial,dis_high,dis_low,ready_high,tardy_high,gap):
        self.Block_Number = block_number #10
        self.Location_Number = location_number #9
        self.Transporter_type = transporter_type # 2
        self.Transporter_Number = transporter_number  # 4 2,2
        self.Transporter_initial = transporter_initial #[0,9]
        distances = np.random.uniform(dis_low, dis_high, size=(self.Location_Number, self.Location_Number)) #1000,4000
        symmetric_matrix = (distances + distances.T) / 2
        np.fill_diagonal(symmetric_matrix, 0)
        self.Dis = symmetric_matrix.copy()
        self.ready_high=ready_high #180
        self.tardy_high=tardy_high #240
        self.gap=gap #50
    def sample(self):

        Block = np.zeros((self.Block_Number, 7))
        transporter = np.zeros((self.Transporter_Number, 6))
        Location = list(range(self.Location_Number))
        for i in range(self.Block_Number):
            v = np.random.choice(self.Location_Number, 2, False)
            Block[i, 0], Block[i, 1] = v[0], v[1]
            Block[i, 2] = self.Dis[int(Block[i, 0]), int(Block[i, 1])] / 80 / self.tardy_high
            Block[i, 3] = np.random.randint(0, self.ready_high) / self.tardy_high
            Block[i, 4] = np.random.randint(Block[i, 2] +self.gap,self.tardy_high ) / self.tardy_high - Block[i, 2]

            weight = np.random.uniform(0, 100)
            if weight > 50:
                Block[i, 5] = 0
                Block[i, 6] = 1
            else:
                Block[i, 5] = 1
                Block[i, 6] = 0
        Block = Block[Block[:, 0].argsort()]
        unique_values, counts = np.unique(Block[:, 0], return_counts=True)
        max_count = np.max(counts)
        edge_fea_idx = -np.ones((self.Location_Number, max_count))
        edge_fea = np.zeros((self.Location_Number, max_count, 5))
        step = 0
        node_in_fea = np.zeros((self.Location_Number, 4 + self.Location_Number))
        step_to_ij = np.zeros((self.Location_Number, max_count))
        for i in range(len(counts)):
            for j in range(max_count):
                if j < counts[i]:
                    edge_fea_idx[int(unique_values[i])][j] = int(Block[step, 1])
                    edge_fea[int(unique_values[i])][j] = Block[step, 2:7]
                    step_to_ij[int(unique_values[i])][j] = step
                    step += 1
        node_in_fea[0, 0] =  int(self.Transporter_Number / 2)
        node_in_fea[8, 2] = self.Transporter_Number-int(self.Transporter_Number / 2)
        node_in_fea[:, 4:] = self.Dis / 4000

        for i in range(self.Transporter_Number):
            if i < int(self.Transporter_Number / 2):
                transporter[i, 0] = 0  # TP type
                transporter[i, 1] = 0  # TP heading point
                transporter[i, 2] = 0  # TP arrival left time
                transporter[i, 3] = 0  # empty travel time
                transporter[i, 4] = -1  # action i
                transporter[i, 5] = -1  # action j

            if i >= int(self.Transporter_Number / 2):
                transporter[i, 0] = 1  # TP type
                transporter[i, 1] = 8  # TP heading point
                transporter[i, 2] = 0  # TP arrival left time
                transporter[i, 3] = 0  # empty travel time
                transporter[i, 4] = -1  # action i
                transporter[i, 5] = -1  # action j

        return self.Block_Number, self.Transporter_Number, Block, transporter, max_count, edge_fea_idx, node_in_fea, edge_fea, self.Dis / 4000, step_to_ij


def simulation(B, T, transporter, block, edge_fea_idx, node_fea, edge_fea, dis, step_to_ij, tardy_high, mode):
    transporter = transporter.copy()
    block = block.copy()
    edge_fea_idx = edge_fea_idx.copy()
    node_fea = node_fea.copy()
    edge_fea = edge_fea.copy()
    event = []
    unvisited_num = B
    node_fea = torch.tensor(node_fea, dtype=torch.float32).to(device)
    edge_fea = torch.tensor(edge_fea, dtype=torch.float32).to(device)
    edge_fea_idx = torch.tensor(edge_fea_idx, dtype=torch.int32).to(device)
    block_done_matrix = torch.where(edge_fea_idx < 0, torch.tensor(0), torch.tensor(1))

    episode = []  # torch node_fea (9,13), edge_fea (9,3,5), edge_fea_idx(9,3), distance (9,3)
    probs = np.zeros(B)
    rewards = np.zeros(B)
    dones = np.ones(B)
    actions = np.zeros(B)

    agent = np.random.randint(0, T)
    node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2] -= 1
    empty_travel_time = 0
    tardiness = 0
    reward_sum = 0
    tardy_sum = 0
    ett_sum = 0
    step = 0
    time = 0
    prob = 0
    num_valid_coords = 10
    while unvisited_num > 0:

        # transporter (T,3) TP type / heading point / TP arrival time
        start_location = transporter[agent][1]
        distance = torch.tensor(dis[int(start_location)], dtype=torch.float32).unsqueeze(1).repeat(1,edge_fea_idx.shape[1]).to(device)

        episode.append(
            [node_fea.clone(), edge_fea.clone(), edge_fea_idx.clone(), distance.clone(), transporter[agent][0]])
        if mode == 'RL':
            action, i, j, prob = ppo.get_action(node_fea, edge_fea, edge_fea_idx, distance, transporter[agent][0])
        elif mode == 'Random':
            valid_coords = ((edge_fea_idx >= 0) & (transporter[agent][0] >= edge_fea[:, :, 4])).nonzero()
            num_valid_coords = valid_coords.shape[0]
            action = random.randint(0, num_valid_coords - 1)
            i = valid_coords[action][0].item()
            j = valid_coords[action][1].item()

        transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, event_list = do_action(transporter,
                                                                                                 block_done_matrix,
                                                                                                 edge_fea_idx.clone(),
                                                                                                 node_fea.clone(),
                                                                                                 edge_fea.clone(),
                                                                                                 agent, i, j, dis, time,
                                                                                                 step_to_ij, tardy_high)
        if unvisited_num == 1:
            actions[step] = action
            probs[step] = prob
            dones[step] = 0
            break
        sw = 0  # do while

        temp_tardy = 0
        temp_ett = 0
        while (((num_valid_coords <= 0) | (sw == 0))):
            sw = 1

            next_agent, mintime = select_agent(transporter[:, 2])
            reward, transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, tardiness, tardy, empty_travel_time = next_state(
                transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, dis, tardiness, tardy_high, mintime,
                next_agent)
            agent = next_agent
            temp_tardy += tardy
            temp_ett += empty_travel_time
            time += mintime
            valid_coords = ((edge_fea_idx >= 0) & (transporter[agent][0] >= edge_fea[:, :, 4])).nonzero()
            num_valid_coords = valid_coords.shape[0]
            if num_valid_coords == 0:
                transporter[agent][2] = float("inf")
        tardy_sum += temp_tardy
        ett_sum += temp_ett
        reward = temp_tardy + temp_ett
        event_list.append(round(temp_tardy, 3))
        event_list.append(round(temp_ett, 3))
        event_list.append(round(reward, 3))

        # event_list 현재 시간, ett,tardy,완료시간,tp,몇번,tardy,ett,reward

        event.append(event_list)
        actions[step] = action
        probs[step] = prob
        rewards[step] = reward
        unvisited_num -= 1

        reward_sum += reward
        step += 1

        # edge fea는 시간 /220 , 속도 100/80
        # dis 거리/4000
        # ready time이 0보다 작으면 0으로
        # tardiness는 그떄 발생한 정도 case 1,2,3 0보다 작으면
    temp_ett = 0
    temp_tardy = 0  # 잔여 reward 계산

    for i in range(T):
        if transporter[i][3] >= 0:
            temp_ett -= transporter[i][3]
            block_done_matrix[int(transporter[i][4])][int(transporter[i][5])] = 0
            edge_fea[int(transporter[i][4]), int(transporter[i][5]), 2] -= transporter[i][3]
            transporter[i][3] = 0
    episode.append([node_fea, edge_fea, edge_fea_idx, distance, 1])  # dummy set
    tardiness_next = edge_fea[:, :, 2][edge_fea[:, :, 2] < 0].sum().item()
    temp_tardy = tardiness_next - tardiness
    tardy_sum += temp_tardy
    ett_sum += temp_ett
    reward = temp_tardy + temp_ett
    rewards[step] += reward
    reward_sum += reward
    event_list.append(round(temp_tardy, 3))
    event_list.append(round(temp_ett, 3))
    event_list.append(round(reward, 3))
    event.append(event_list)  # event_list 현재 시간, ett,tardy,완료시간,tp,몇번,tardy,ett,reward
    return reward_sum, tardy_sum, ett_sum, event, episode, actions, probs, rewards, dones


# 각각 action과 next_state로 분리하자
def do_action(transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, agent, i, j, dis, time, step_to_ij,
              tardy_high):
    past_location = int(transporter[agent][1])
    transporter[agent][3] = dis[int(transporter[agent][1]), i] * 40 / tardy_high
    transporter[agent][2] = (
                max(dis[int(transporter[agent][1]), i] * 40 / tardy_high, edge_fea[i][j][1].item()) + edge_fea[i][j][
            0].item())
    transporter[agent][1] = edge_fea_idx[i][j].item()
    transporter[agent][4] = i
    transporter[agent][5] = j
    event_list = [round(time, 3), round(transporter[agent][3] + time, 3), round(edge_fea[i][j][2].item() + time, 3),
                  round(transporter[agent][2] + time, 3), agent,
                  step_to_ij[i][j]]  # event_list 현재 시간, ett,tardy,완료시간,tp,몇번
    if past_location == i:
        block_done_matrix[int(transporter[agent][4])][int(transporter[agent][5])] = 0
    # 1 TP heading point
    # 2 TP arrival left time
    # 3 empty travel time
    # 4 action i
    # 5 action j

    node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2 + 1] = (node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2 + 1] *node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2] +transporter[agent][2]) / (node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2] + 1)
    node_fea[int(transporter[agent][1])][int(transporter[agent][0]) * 2] += 1
    edge_fea_idx[i][j] = -1
    return transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, event_list


def next_state(transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, dis, tardiness, tardy_high, min_time,
               next_agent):
    empty_travel_time = 0

    for i in range(len(transporter)):
        if transporter[i][3] > min_time:
            transporter[i][3] -= min_time
            empty_travel_time -= min_time
        elif transporter[i][3] > 0:
            empty_travel_time -= transporter[i][3]
            block_done_matrix[int(transporter[i][4])][int(transporter[i][5])] = 0
            edge_fea[int(transporter[i][4]), int(transporter[i][5]), 2] -= transporter[i][3]
            transporter[i][3] = 0
        transporter[i][2] -= min_time
    # node_fea

    node_fea[:, [1, 3]] = node_fea[:, [1, 3]] - min_time
    node_fea[node_fea < 0] = 0
    node_fea[int(transporter[next_agent][1]), int(transporter[next_agent][0]) * 2] -= 1

    # edge_fea

    edge_fea[:, :, [1, 2]] = edge_fea[:, :, [1, 2]] - block_done_matrix.unsqueeze(2).repeat(1, 1, 2) * min_time
    edge_fea[:, :, 1][edge_fea[:, :, 1] < 0] = 0
    tardiness_next = edge_fea[:, :, 2][edge_fea[:, :, 2] < 0].sum().item()

    tardy = tardiness_next - tardiness

    reward = tardy + empty_travel_time

    # tardiness 수정, weight constraint 고려 ready time
    return reward, transporter, block_done_matrix, edge_fea_idx, node_fea, edge_fea, tardiness_next, tardy, empty_travel_time


def select_agent(event):
    argmin = np.where(event.min() == event)
    agent = int(random.choice(argmin[0]))
    min_time = event[agent]
    return agent, min_time


def plot_gantt_chart(events, B, T):
    """

    # event_list 현재 시간, ett,tardy,완료시간,tp,몇번,tardy,ett,reward


    """

    # version 1:
    colorset = plt.cm.rainbow(np.linspace(0, 1, B))

    # Set up figure and axis
    fig, ax = plt.subplots()

    # Plot Gantt chart bars
    for event in events:
        job_start = event[0]
        empty_travel_end = event[1]
        ax.barh(y=event[4], width=empty_travel_end - job_start, left=job_start, height=0.6,
                label=f'transporter {event[4] + 1}', color='grey')
        job_end = event[3]
        ax.barh(y=event[4], width=job_end - empty_travel_end, left=empty_travel_end, height=0.6,
                label=f'transporter {event[4] + 1}', color=colorset[int(event[5])])
        # ax.text((job_start+empty_travel_end)/2, event[3], 'empty travel time',ha='center',fontsize=7,va='center')
        ax.text((empty_travel_end + job_end) / 2, event[4], 'Block' + str(int(event[5])), ha='center', fontsize=6,
                va='center')

    # Customize the plot
    ax.set_xlabel('Time')
    ax.set_yticks(range(T))
    ax.set_yticklabels([f'transporter {i + 1}' for i in range(T)])

    # Show the plot
    plt.show()
