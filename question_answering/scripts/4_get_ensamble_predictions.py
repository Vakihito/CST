print("###############################")
print("##### Starting notebook 4 #####")
print("###############################")

from torch.utils.data import DataLoader
import os
import shutil
import pandas as pd


"""## Getting model predictions

"""

import torch
import pandas as pd
import numpy as np
import random
import os
from tqdm import tqdm

max_length = 512  # The maximum length of a feature (question and context)
doc_stride = 128  # The allowed overlap between two part of the context when splitting is performed.

n_clusters = int(os.environ["n_clusters"])
read_data_path = os.environ["read_data_path"]
base_model=os.environ["base_model"]

emsamble_quantile = int(os.environ["emsamble_quantile"])

from collections import defaultdict
def create_split_count(cur_df):
  split_count = defaultdict(lambda : 0)
  list_splits = []
  for cur_indx in cur_df['index']:
    list_splits.append(split_count[cur_indx])
    split_count[cur_indx] += 1
  return list_splits


def match_idx_to_name(df_to_match, df_with_names):
  ids = df_with_names["id"].values
  contexts = df_with_names["context"].values
  questions = df_with_names["question"].values
  clusters = df_with_names["cluster_labels"].values
  datasets = df_with_names['dataset'].values

  map_id_context = {cur_id: cur_context for cur_id, cur_context in zip(ids, contexts)}
  map_id_questions = {cur_id: cur_question for cur_id, cur_question in zip(ids, questions)}
  map_id_clusters = {cur_id: cur_clusters for cur_id, cur_clusters in zip(ids, clusters)}
  map_id_datasets = {cur_id: cur_dataset for cur_id, cur_dataset in zip(ids, datasets)}
  map_id_datasets = {cur_id: cur_dataset for cur_id, cur_dataset in zip(ids, datasets)}

  df_to_match["context"] = df_to_match["index"].apply(lambda x: map_id_context[x])
  df_to_match["question"] = df_to_match["index"].apply(lambda x: map_id_questions[x])
  df_to_match["cluster_labels"]  = df_to_match["index"].apply(lambda x: map_id_clusters[x])
  df_to_match["dataset"]  = df_to_match["index"].apply(lambda x: map_id_datasets[x])
  df_to_match["id"]  = df_to_match["index"].apply(lambda x: x)

from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(base_model)
pad_on_right = tokenizer.padding_side == "right"

def get_single_prediction_text(cur_start, cur_end, cur_context, cur_question, sample_idx):
  tokenized_examples = tokenizer(
        [cur_question if pad_on_right else cur_context],
        [cur_context if pad_on_right else cur_question],
        truncation="only_second" if pad_on_right else "only_first",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )
  start_offset = tokenized_examples.encodings[sample_idx].offsets[cur_start][0]
  end_offset = tokenized_examples.encodings[sample_idx].offsets[cur_end][1]
  return cur_context[start_offset:end_offset]

def prediction_function(cur_df):
  idx_start = cur_df["mean_ini_position"].values
  idx_end = cur_df["mean_end_position"].values
  list_input_ids = cur_df["input_ids"].values
  list_contexts = cur_df["context"].values
  list_questions = cur_df["question"].values
  list_split = cur_df['split'].values

  idx_start_prob = cur_df["preds_mean_prob_ini_all_tokens"].values
  idx_end_prob = cur_df["preds_mean_prob_end_all_tokens"].values

  dict_responses = {
      "reponse_str" : [],
      "start_prob" : [],
      "start_prob_all_tokens" : [],
      "end_prob" : [],
      "end_prob_all_tokens" : [],
      "mean_prob" : [],
      "start_pos": [],
      "end_post": []
  }


  for i, cur_start, cur_end, cur_context, cur_question, cur_split in zip(range(len(idx_start)) ,idx_start, idx_end, list_contexts, list_questions, list_split):
    cur_input_ids = list_input_ids[i]
    cur_start_idx_prob = idx_start_prob[i]
    cur_end_idx_prob = idx_end_prob[i]

    cur_start_idx_prob_max = np.max(idx_start_prob[i])
    cur_end_idx_prob_max = np.max(idx_end_prob[i])


    # cases of empty response
    if (cur_start <= 0) or (cur_end <= 0) or (cur_start + 1 > len(cur_input_ids)) or ((cur_end + 1 > len(cur_input_ids))):
      dict_responses["reponse_str"].append("")
      dict_responses["start_prob_all_tokens"].append(cur_start_idx_prob)
      dict_responses["end_prob_all_tokens"].append(cur_end_idx_prob)
      dict_responses["start_prob"].append(0.)
      dict_responses["end_prob"].append(0.)
      dict_responses["mean_prob"].append(0.)
      dict_responses["start_pos"].append(cur_start)
      dict_responses["end_post"].append(cur_end)
    else:
      if (cur_start > cur_end + 1):
        cur_end = cur_start + 1

      answer_prob = (cur_start_idx_prob_max + cur_end_idx_prob_max) / 2
      convert_tokens = lambda x: tokenizer.convert_tokens_to_string((tokenizer.convert_ids_to_tokens(x)))
      prediction_text = get_single_prediction_text(cur_start, cur_end, cur_context, cur_question, cur_split)
      dict_responses["reponse_str"].append(prediction_text)
      dict_responses["start_prob_all_tokens"].append(cur_start_idx_prob)
      dict_responses["end_prob_all_tokens"].append(cur_end_idx_prob)
      dict_responses["start_prob"].append(cur_start_idx_prob_max)
      dict_responses["end_prob"].append(cur_end_idx_prob_max)
      dict_responses["mean_prob"].append(answer_prob)
      dict_responses["start_pos"].append(cur_start)
      dict_responses["end_post"].append(cur_end)


  return dict_responses

def get_single_prediction(cur_df_sampled):
  mean_probs = cur_df_sampled["mean_prob"].values
  idx = np.argmax(mean_probs)
  return cur_df_sampled.iloc[idx]


def get_final_prediction(cur_df, cur_df_base):
  cur_df["split"] = create_split_count(cur_df)
  match_idx_to_name(cur_df, cur_df_base)

  dict_responses = prediction_function(cur_df)
  for cur_key in dict_responses:
    cur_df[cur_key] = dict_responses[cur_key]

  final_predictions = []
  all_indexes = cur_df["index"].unique()
  for cur_idx in all_indexes:
    cur_df_sampled = cur_df[cur_df["index"] == cur_idx]
    final_predictions.append(get_single_prediction(cur_df_sampled))
  return pd.DataFrame(final_predictions)

df_train = pd.read_pickle(f"{read_data_path}/train_data_clustered.pkl")
df_test = pd.read_pickle(f"{read_data_path}/test_data_clustered.pkl")
df_val = pd.read_pickle(f"{read_data_path}/val_data_clustered.pkl")

important_cols = ["context",	"question",	"cluster_labels",
                  "dataset",	"reponse_str",
                  "start_prob",	"end_prob",	"mean_prob",
                  "start_pos",	"end_post", "id",
                  "start_prob_all_tokens", "end_prob_all_tokens"]

list_cluster_preds_train, list_cluster_preds_test, list_cluster_preds_val = ([], [], [])

for cur_cluster in range(n_clusters):
  cur_df_train_preds = pd.read_pickle(f"{os.environ['read_data_path']}/train_data_with_cluster_preds_{cur_cluster}.pkl")
  cur_df_test_preds = pd.read_pickle(f"{os.environ['read_data_path']}/test_data_with_cluster_preds_{cur_cluster}.pkl")
  cur_df_val_preds = pd.read_pickle(f"{os.environ['read_data_path']}/val_data_with_cluster_preds_{cur_cluster}.pkl")

  list_cluster_preds_train.append(cur_df_train_preds)
  list_cluster_preds_test.append(cur_df_test_preds)
  list_cluster_preds_val.append(cur_df_val_preds)

df_train_with_cluster_preds = pd.concat(list_cluster_preds_train)
df_test_with_cluster_preds = pd.concat(list_cluster_preds_test)
df_val_with_cluster_preds = pd.concat(list_cluster_preds_val)

df_train_preds_base_preds = pd.read_pickle(f"{os.environ['read_data_path']}/train_data_with_base_preds.pkl")
df_test_preds_base_preds = pd.read_pickle(f"{os.environ['read_data_path']}/test_data_with_base_preds.pkl")
df_val_preds_base_preds = pd.read_pickle(f"{os.environ['read_data_path']}/val_data_with_base_preds.pkl")

df_train_preds_base_preds['split'] = create_split_count(df_train_preds_base_preds)
df_test_preds_base_preds['split'] = create_split_count(df_test_preds_base_preds)
df_val_preds_base_preds['split'] = create_split_count(df_val_preds_base_preds)
df_train_with_cluster_preds['split'] = create_split_count(df_train_with_cluster_preds)
df_test_with_cluster_preds['split'] = create_split_count(df_test_with_cluster_preds)
df_val_with_cluster_preds['split'] = create_split_count(df_val_with_cluster_preds)

df_train_preds_base_preds.sort_values(by=["index", "split"], inplace=True)
df_test_preds_base_preds.sort_values(by=["index", "split"], inplace=True)
df_val_preds_base_preds.sort_values(by=["index", "split"], inplace=True)

df_train_with_cluster_preds.sort_values(by=["index", "split"], inplace=True)
df_test_with_cluster_preds.sort_values(by=["index", "split"], inplace=True)
df_val_with_cluster_preds.sort_values(by=["index", "split"], inplace=True)

df_train_with_cluster_preds.head(3)

df_train_preds_base_preds['cluster_preds_end'] = df_train_with_cluster_preds['prob_end'].values
df_test_preds_base_preds['cluster_preds_end'] = df_test_with_cluster_preds['prob_end'].values
df_val_preds_base_preds['cluster_preds_end'] = df_val_with_cluster_preds['prob_end'].values

df_train_preds_base_preds['cluster_preds_ini'] = df_train_with_cluster_preds['prob_ini'].values
df_test_preds_base_preds['cluster_preds_ini'] = df_test_with_cluster_preds['prob_ini'].values
df_val_preds_base_preds['cluster_preds_ini'] = df_val_with_cluster_preds['prob_ini'].values

def get_mean_probs(cur_df, cur_pos, col_cluster, col_base):
  l_mean_probs = []
  l_mean_position = []
  l_prob_position = []
  for _, row in cur_df.iterrows():
    list_probs = (np.array(row[col_cluster]) + np.array(row[col_base]))/2
    l_mean_position.append(list_probs)
    l_mean_probs.append(np.argmax(list_probs))
    l_prob_position.append(np.max(list_probs))
  cur_df[f'preds_mean_prob_{cur_pos}_all_tokens'] = l_mean_position
  cur_df[f'mean_{cur_pos}_position']  = l_mean_probs
  cur_df[f'mean_prob_{cur_pos}'] = l_prob_position

get_mean_probs(df_train_preds_base_preds, 'end', 'cluster_preds_end', 'prob_end')
get_mean_probs(df_test_preds_base_preds, 'end', 'cluster_preds_end', 'prob_end')
get_mean_probs(df_val_preds_base_preds, 'end', 'cluster_preds_end', 'prob_end')


get_mean_probs(df_train_preds_base_preds, 'ini', 'cluster_preds_ini', 'prob_ini')
get_mean_probs(df_test_preds_base_preds, 'ini', 'cluster_preds_ini', 'prob_ini')
get_mean_probs(df_val_preds_base_preds, 'ini', 'cluster_preds_ini', 'prob_ini')

def get_more_than_mean(cur_df):
  mean_probs_ini = np.percentile(df_test_preds_base_preds[f'mean_prob_ini'].values, emsamble_quantile)
  mean_probs_end = np.percentile(df_test_preds_base_preds[f'mean_prob_end'].values, emsamble_quantile)

  cur_sample_df_mean = cur_df[(cur_df['mean_prob_ini'] > mean_probs_ini) & (cur_df['mean_prob_end'] > mean_probs_end)].reset_index(drop=True)
  return cur_sample_df_mean

df_test_preds_ensamble = get_more_than_mean(df_test_preds_base_preds)
df_val_preds_ensamble = get_more_than_mean(df_val_preds_base_preds)

df_test_with_emsamble_preds = get_final_prediction(df_test_preds_ensamble, df_test)
df_val_with_emsamble_preds = get_final_prediction(df_val_preds_ensamble, df_val)

df_train.head(3)

important_columns = ["context", "question", "dataset",  "id", "cluster_labels", "start_pos", "reponse_str"]

def create_answer_base_on_prediction(cur_df):
  cur_df = cur_df[cur_df['start_prob'] > 0.0000001].reset_index(drop=True)
  cur_df[important_columns] = cur_df[important_columns].reset_index(drop=True)
  list_str_answers = []
  list_indexes = []
  for _, row in cur_df.iterrows():
    start = row["context"].lower().find(row['reponse_str'].lower())
    if start >= 0:
      list_str_answers.append({
          'text': [row['reponse_str']],
          'answer_start': [start]
      })
      list_indexes.append(True)
    else:
      list_indexes.append(False)
  cur_df = cur_df[list_indexes].reset_index(drop=True)
  cur_df['answers'] = list_str_answers
  return cur_df

df_test_with_emsamble_preds = create_answer_base_on_prediction(df_test_with_emsamble_preds)
df_val_with_emsamble_preds = create_answer_base_on_prediction(df_val_with_emsamble_preds)

df_train_with_ensamble_predictions = pd.concat([df_train, df_test_with_emsamble_preds, df_val_with_emsamble_preds])

final_columns = ["context", "question", "answers", "dataset",  "id", "cluster_labels"]

df_train_with_ensamble_predictions = df_train_with_ensamble_predictions[final_columns].reset_index(drop=True)

print("adding from train : ", len(df_train))
print("adding from test : ", len(df_test_with_emsamble_preds))
print("adding from val : ", len(df_val_with_emsamble_preds))

df_train_with_ensamble_predictions[final_columns].to_pickle(f"{os.environ['read_data_path']}/train_data_emsambled.pkl")