# -*- coding: utf-8 -*-
"""Untitled0.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1ov9kuv0ANq4GMFancVgiGCILqzGq7pG5
"""

from torch.nn.modules.activation import MultiheadAttention
import torch
import torch.nn as nn
import math


## coding our own LAYER NORMALISZATION CODE as the inbuilt one doesnt allow bias = false
class LayerNormalization(nn.Module):
    def __init__(self, eps:float = 10**-6)-> None:
        super().__init__()
        self.eps = eps
        self.alpha = nn.Parameter(torch.ones(1))
        self.bias = nn.Parameter(torch.zeros(1))    ## alpha and beta are learnable parameters

    def forward(self, x):
        # x: [batch, seq_length , hidden_size]
        mean = x.mean(-1, keepdim = True) # [batch, seq, 1]
        std = x.std(-1, keepdim = True) # [batch , seq , 1]
        #keep the dimension for broadcasting , if (keepdim = False) - the last dimension will not be there - [batch , seqdim]
        return self.alpha * (x - mean) / (std + self.eps) + self.bias


## FEED FORWARD NETWORK - using squeeze and expand method
class FeedForwardBlock(nn.Module):
    def __init__(self, d_model : int, d_ff : int, dropout:float)-> None:
        super().__init__()
        self.linear_1 = nn.Linear(d_model , d_ff) ## w1 and b1
        self.dropout = nn.Dropout(dropout)
        self.linear_2 = nn.Linear(d_ff, d_model)

    def forward(self, x):
        ## [batch, seq_length, d_model] -> [batch, seq_length, d_ff] -> [batch, seq_length, d_model]
        return self.linear_2(self.dropout(torch.relu(self.linear_1(x))))

## for converting inputs to dimensional embedding prepared to go in encoder or decoder.
class InputEmbeddings(nn.Module):
    def __init__(self, d_model:int, vocab_size:int)-> None:
        super().__init__()
        self.d_model = d_model
        self.vocab_size = vocab_size
        self.embedding = nn.Embedding(vocab_size, d_model)

    def forward(self, x):
        # [batch_size, seq_length] -> [batch_size, seq_length, d_model]
        # multiply by sqrt(d_model) to scale the embedding according to the paper
        return self.embedding(x) * math.sqrt(self.d_model)

class PositionalEncoding(nn.Module):
    def __init__(self, d_model:int, seq_len:int, dropout:float )-> None:
        super().__init__()
        self.d_model = d_model
        self.seq_len = seq_len
        self.dropout = nn.Dropout(dropout)
        # create a matrix of shape (seq_len , d_model)
        pe = torch.zeros(seq_len, d_model)
        # create a vector of shape [seq_len]
        position = torch.arange(0, seq_len, dtype = torch.float).unsqueeze(1) ## [seq_len , 1]
        # create a vector of shape [d_model]
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)) # [d_model]
        # apply sine to even indices
        pe[ : , 0::2] = torch.sin(position * div_term) # sin(position * (10000**(2i/d_model))
        # apply cosine to all odd indices
        pe[ : , 1::2] = torch.cos(position * div_term) # cos(position * (10000**(2i/d_model))
        # add a batch to positional encoding
        pe = pe.unsqueeze(0)
        ## register the positional encoding as BUFFER(non trainable)
        self.register_buffer('pe' , pe) ## saves the value of pe as "pe" even if the kernel gets closed, and this is not back_propagated


    def forward(self, x):
        x = x + (self.pe[:, : x.shape[1] , :]).requires_grad_(False) # [batch, seq_len , d_model]
        # x = x + (self.pe[:, : , :]).requires_grad_(False)
        # x.shape[1] gives the seq_length of a sentence.
        return self.dropout(x)


class ResidualConnection(nn.Module):
    def __init__(self, dropout:float)-> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.norm = LayerNormalization()

    def forward(self, x, sublayer):
        return x + self.dropout(sublayer(self.norm(x))) ## cant understand it currently


## MULTI HEAD ATTENTION part which we can use for BOTH ENCODER and DECODER
class MultiHeadAttentionBlock(nn.Module):
    def __init__(self, d_model:int, h:int, dropout:float)-> None:
        super().__init__()
        self.d_model = d_model # embedding vector size
        self.h = h # Number of heads
        #make sure d_model is divisible by h
        assert d_model % h == 0, "d_model is not divisible by h"

        self.d_k = d_model // h # dimension of embedding seen by each head
        self.w_q = nn.Linear(d_model, d_model, bias = False) #Wq
        self.w_k = nn.Linear(d_model, d_model, bias = False) #Wk
        self.w_v = nn.Linear(d_model, d_model, bias = False) #Wv
        self.w_o = nn.Linear(d_model, d_model, bias = False) #Wo
        ## Heads are not considered yet in the above code
        self.dropout = nn.Dropout(dropout)

    @staticmethod  # we can directly use call function without instantiating the multi head attention class by using: MultiHeadAtetntion.attention(...)
    def attention(query, key, value, mask, dropout:nn.Dropout):
        d_k = query.shape[-1] # gives the last dimension which is the dimension_size of each head i.e. d_k
        # Just apply formula from the paper
        attention_scores = (query @ key.transpose(-2,-1)) / math.sqrt(d_k)
        if mask is not None:
            ## write a very low value(indicating -inf) to the positions where mask == 0
            attention_scores.masked_fill_(mask == 0, -1e4)
        # applying softmax along the values of last dimension(could have been applied along any of last 2 dimensions, doesnt matter)
        attention_scores = attention_scores.softmax(dim = -1) # [batch, h, seq_length, seq_length]
        if dropout is not None:
            attention_scores = dropout(attention_scores)
        ## (batch, h, seq_length, seq_length) -> (batch, h , seq_length, d_k)
        # return attention scores which can be used for visualisation
        return (attention_scores @ value) , attention_scores

    def forward(self, q, k , v , mask):
        query = self.w_q(q) ## [batch, seq_length, d_model] -> [batch, seq_length, d_model]
        key = self.w_k(k) # [batch, seq_length, d_model] -> [batch, seq_length, d_model]
        value = self.w_v(v) # [batch, seq_length, d_model] -> [batch, seq_length, d_model]

        # dividing it into h heads
        #[batch, seq_length, d_model] -> [batch, seq_length, h, d_k] -> [batch, h, seq_length, d_k]
        query = query.view(query.shape[0], query.shape[1], self.h, self.d_k).transpose(1,2) # query.shape[1] = seq_length(), query.shape[0] = batch
        key = key.view(key.shape[0], key.shape[1], self.h, self.d_k).transpose(1,2)
        value = value.view(value.shape[0], value.shape[1], self.h, self.d_k).transpose(1,2)

        #calculate attention
        x, self.attention_scores = MultiHeadAttentionBlock.attention(query, key, value, mask, self.dropout)

        #combine all heads together
        # (batch, h, seq_length, d_k) -> (batch, seq_length, h , d_k) - > (batch , seq_length, d_model)
        x = x.transpose(1,2).contiguous().view(x.shape[0] , -1, self.h * self.d_k)

        # multipply by wo
        # (batch , seq_length, d_model) -> (batch , seq_length, d_model)
        return self.w_o(x)

## a single encoder block
class EncoderBlock(nn.Module):
    def __init__(self, self_attention_block:MultiHeadAttentionBlock, feed_forward_block:FeedForwardBlock , dropout:float)-> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connection = nn.ModuleList([ResidualConnection(dropout) for _ in range(2)])

    def forward(self, x, src_mask):
        x = self.residual_connection[0](x, lambda x: self.self_attention_block(x,x,x, src_mask))
        ## as for an encoder key, query, value have same inputs
        x = self.residual_connection[1](x, self.feed_forward_block)
        # in encoder block, one can see 2 skip connections, one before and after the MHA and one before after the Feed forward layer.
        return x

## Actual encoder
class Encoder(nn.Module):
    def __init__(self, layers: nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization()

    def forward(self, x, mask):
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)


class DecoderBlock(nn.Module):
    def __init__(self, self_attention_block:MultiHeadAttentionBlock, cross_attention_block : MultiHeadAttentionBlock, feed_forward_block:FeedForwardBlock, dropout:float) -> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.cross_attention_block = cross_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connection = nn.ModuleList([ResidualConnection(dropout) for _ in range(3)])

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        x = self.residual_connection[0](x, lambda x: self.self_attention_block(x ,x, x, tgt_mask))
        # initial masked multi head attention layer where encoder outputs are not used
        x = self.residual_connection[1](x, lambda x: self.cross_attention_block(x, encoder_output, encoder_output, src_mask))
        # cross attention layers where query is x, and key and value are from encoder blocks
        x = self.residual_connection[2](x, self.feed_forward_block)
        return x
        # final feed forward layer

class Decoder(nn.Module):
    def __init__(self, layers : nn.ModuleList)-> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization()

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        for layers in self.layers:
            x = layers( x, encoder_output, src_mask, tgt_mask)
        return self.norm(x)


## for converting the final enmbedding to the vocabulary space meaning which work is most likely to come
class ProjectionLayer(nn.Module):
    def __init__(self, d_model, vocab_size):
        super().__init__()
        self.proj = nn.Linear(d_model, vocab_size)

    def forward(self, x)-> None:
        # [batch, seq_length, d_model] -> [batch, seq_length, vocab_size]
        return torch.log_softmax(self.proj(x), dim = -1)


class Transformer(nn.Module):
    def __init__(self, encoder: Encoder, decoder: Decoder, src_embed : InputEmbeddings, tgt_embed : InputEmbeddings, src_pos : PositionalEncoding, tgt_pos : PositionalEncoding, projection_layer : ProjectionLayer  )-> None:
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.src_pos = src_pos
        self.tgt_pos = tgt_pos
        self.projection_layer = projection_layer

    def encode(self, src, src_mask):
        #[batch, seq_length, d_model]
        src = self.src_embed(src)
        src = self.src_pos(src)
        encoder_output = self.encoder(src, src_mask)
        return encoder_output

    def decode(self, encoder_output: torch.Tensor, src_mask: torch.Tensor, tgt: torch.Tensor, tgt_mask: torch.Tensor )-> None:
        # [batch, seq_length, d_model]
        tgt = self.tgt_embed(tgt)
        tgt = self.tgt_pos(tgt)
        # target - the thing we need to predict
        decoder_output = self.decoder(tgt, encoder_output, src_mask, tgt_mask)
        return decoder_output

    def project(self, x):
        # [batch, seq_length, vocab_size]
        return self.projection_layer(x)

def build_transformer(src_vocab_size: int, tgt_vocab_size: int, src_seq_length: int, tgt_seq_length: int, d_model: int = 512, N:int=6, h:int=8, dropout:float = 0.1, d_ff:int=256):
    # create embedding layer

    src_embed = InputEmbeddings(d_model, src_vocab_size)
    tgt_embed = InputEmbeddings(d_model, tgt_vocab_size)

    # create positional encoding layers
    src_pos = PositionalEncoding(d_model, src_seq_length, dropout)
    tgt_pos = PositionalEncoding(d_model, tgt_seq_length, dropout)

    # create encoder blocks
    encoder_blocks = []
    # N - no of encoder and decoder blocks
    for _ in range(N // 2):
        encoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        encoder_block = EncoderBlock(encoder_self_attention_block, feed_forward_block, dropout)
        encoder_blocks.append(encoder_block)


    # create decoder blocks
    decoder_blocks = []
    for _ in range(N // 2):
        decoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        decoder_cross_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        decoder_block = DecoderBlock(decoder_self_attention_block, decoder_cross_attention_block, feed_forward_block, dropout )
        decoder_blocks.append(decoder_block)

    e1, e2, e3 = encoder_blocks
    d1, d2, d3 = decoder_blocks

    encoder_blocks1 = [e1, e2, e3, e3, e2, e1]
    decoder_blocks1 = [d1, d2, d3, d3, d2, d1]


    # create the encoder and decoder
    encoder = Encoder(nn.ModuleList(encoder_blocks1))
    decoder = Decoder(nn.ModuleList(decoder_blocks1))



    #create the projection layer
    projection_layer = ProjectionLayer(d_model, tgt_vocab_size)

    # create the transformer
    transformer = Transformer(encoder, decoder, src_embed, tgt_embed, src_pos, tgt_pos, projection_layer)

    # initialise the parameters(will work even if we dont do this)
    for p in transformer.parameters():
        if p.dim() > 1:
            nn.init.normal_(p, std = 0.02)

    n_param = sum(p.numel() for p in transformer.parameters())
    print("Total Parameters:", n_param)

    return transformer



import torch
import torch.nn
from torch.utils.data import Dataset

## convert from one language to another
class BillingualDataset(Dataset):
    def __init__(self, ds, tokenizer_src, tokenizer_tgt, src_lang, tgt_lang, seq_len):
        super().__init__()
        self.seq_len = seq_len
        self.ds = ds
        self.tokenizer_src = tokenizer_src
        self.tokenizer_tgt = tokenizer_tgt
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang

        self.sos_token = torch.tensor([tokenizer_tgt.token_to_id("[SOS]")], dtype = torch.int64)
        self.eos_token = torch.tensor([tokenizer_tgt.token_to_id("[EOS]")], dtype = torch.int64)
        self.pad_token = torch.tensor([tokenizer_tgt.token_to_id("[PAD]")], dtype = torch.int64)

    def __len__(self):
        return len(self.ds)


    def __getitem__(self, idx):
        ## extracting the text fromt he input
        src_target_pair = self.ds[idx]
        src_text = src_target_pair['translation'][self.src_lang]
        tgt_text = src_target_pair['translation'][self.tgt_lang]

        ## transform text into token
        enc_input_tokens = self.tokenizer_src.encode(src_text).ids
        dec_input_tokens = self.tokenizer_tgt.encode(tgt_text).ids

        ##add sos eos and padding to each of the sentence
        enc_num_padding_tokens = self.seq_len - len(enc_input_tokens) - 2 ## add both sos and eod
        dec_num_padding_tokens = self.seq_len - len(dec_input_tokens) - 1 ## add only sos and not eos

        ## make sure number of padding tokenn is not negative. If it is, sentence is too long
        if enc_num_padding_tokens < 0  or dec_num_padding_tokens < 0:
            raise ValueError("Sentence too long")

        ## add sos and eos token
        encoder_input = torch.cat(
            [
                self.sos_token,
                torch.tensor(enc_input_tokens, dtype = torch.int64),
                self.eos_token,
                # torch.tensor([self.pad_token] * enc_num_padding_tokens , dtype = torch.int64),
            ],
            dim = 0,
        )

        decoder_input = torch.cat(
            [
                self.sos_token,
                torch.tensor(dec_input_tokens, dtype = torch.int64),
                # torch.tensor([self.pad_token] * dec_num_padding_tokens , dtype = torch.int64),
            ],
            dim = 0,
        )

        ## add only eos token
        label = torch.cat(
            [
                torch.tensor(dec_input_tokens, dtype = torch.int64),
                self.eos_token,
                # torch.tensor([self.pad_token] * dec_num_padding_tokens , dtype = torch.int64),
            ],
            dim = 0,
        )

        ## NOTICE THE DIFFERENCE b/w DECODER_INPUT and LABEL, this difference allows us to parallely train decoder models
        ## for any index i, input is from 0 to i of decoder input and label(or prediction) is ith of label which is actually the next word.

        # double check the size of tensors to make sure they are fo same length i.e. seq_len

        # assert encoder_input.size(0) == self.seq_len
        # assert decoder_input.size(0) == self.seq_len
        # assert label.size(0) == self.seq_len

        return {
            "encoder_input" : encoder_input,
            "decoder_input" : decoder_input,
            "encoder_str_length":len(enc_input_tokens),
            "decoder_str_length":len(dec_input_tokens),
            "encoder_mask" : (encoder_input != self.pad_token).unsqueeze(0).unsqueeze(0).int(),  ## (1,1,seq_len)
            # where ever encoder token is not equal to pad token, pass TRUE, and where it is equal to pad pass FALSE , thereforE of type(T, T ,T, F, F, F, F)
            "decoder_mask" : (decoder_input != self.pad_token).unsqueeze(0).int() & causal_mask(decoder_input.size(0)),  # (1,seq_len) & (1, seq_len, seq_len)
            ## seq_len = 10
            ## SOS    I  GOT   A   CAT    PAD    PAD    PAD    PAD    PAD    PAD
            ## TRUE TRUE TRUE TRUE TRUE  FALSE  FALSE  FALSE  FALSE  FALSE  FALSE
            ## 1 1 1 1 1 0 0 0 0 0
            ## Upper triangular matrix
            ## 1 1 1 1 1 1 1 1 1 1
            ## 0 1 1 1 1 1 1 1 1 1
            ## 0 0 1 1 1 1 1 1 1 1
            ## 0 0 0 1 1 1 1 1 1 1
            ## 0 0 0 0 1 1 1 1 1 1
            ## 0 0 0 0 0 1 1 1 1 1
            ## 0 0 0 0 0 0 1 1 1 1
            ## 0 0 0 0 0 0 0 1 1 1
            ## 0 0 0 0 0 0 0 0 1 1
            ## 0 0 0 0 0 0 0 0 0 1

            ## after AND operation - Final Decoder Mask
            ## 1 1 1 1 1 0 0 0 0 0
            ## 0 1 1 1 1 0 0 0 0 0
            ## 0 0 1 1 1 0 0 0 0 0
            ## 0 0 0 1 1 0 0 0 0 0
            ## 0 0 0 0 1 0 0 0 0 0
            ## 0 0 0 0 0 0 0 0 0 0
            ## 0 0 0 0 0 0 0 0 0 0
            ## 0 0 0 0 0 0 0 0 0 0
            ## 0 0 0 0 0 0 0 0 0 0
            ## 0 0 0 0 0 0 0 0 0 0
            "label" : label, #(seq_len)
            "src_text" : src_text,
            "tgt_text" : tgt_text,
        }

def causal_mask(size):
    ## creates upper traigular matrix of ones with diagonal = 1.
    mask = torch.triu(torch.ones((1, size, size)), diagonal = 1).type(torch.int)
    return mask == 0

# from model import build_transformer
# from dataset import BillingualDataset, causal_mask
# from config import get_config, get_weights_file_path


!pip install torchtext
!pip3 install datasets
!pip3 install tokenizers

from torchtext import datasets as datasets
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
from torch.optim.lr_scheduler import LambdaLR

import warnings
from tqdm import tqdm
import os
from pathlib import Path


# hugging face datasets and tokenizer
from datasets import load_dataset
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.trainers import WordLevelTrainer
from tokenizers.pre_tokenizers import Whitespace

!pip3 install torchmetrics
import torchmetrics

from torch.utils.tensorboard import SummaryWriter

## basically speeds up some part of code
def greedy_decode(model, source, source_mask, tokenizer_src, tokenizer_tgt, max_len, device):
    sos_idx = tokenizer_tgt.token_to_id('[SOS]')
    eos_idx = tokenizer_tgt.token_to_id('[EOS]')

    ## precompute the encoder output and reuse it for every step
    encoder_output = model.encode(source, source_mask)
    ## initialise decoder input with sos token
    decoder_input = torch.empty(1,1).fill_(sos_idx).type_as(source).to(device)
    while True:
        if decoder_input.size(1) == max_len: # if we reach max length before getting the eos token
            break

        ## build mask for target
        decoder_mask = causal_mask(decoder_input.size(1)).type_as(source_mask).to(device)

        # calculate output
        out = model.decode(encoder_output, source_mask, decoder_input, decoder_mask)

        # get next token
        prob = model.project(out[:, -1])
        _, next_word = torch.max(prob, dim = 1)

        decoder_input = torch.cat(
            [decoder_input, torch.empty(1,1).type_as(source).fill_(next_word.item()).to(device)], dim = 1,
        )

        if next_word == eos_idx:
            break

    return decoder_input.squeeze(0)


def run_validation(model, validation_ds, tokenizer_src, tokenizer_tgt, max_len, device, print_msg, global_step, writer, num_examples= 2):
    model.eval()
    count = 0

    source_texts = []
    expected = []
    predicted = []

    try:
        # get the console window width
        with os.popen('stty size', 'r') as console:
            _, console_width = console.read().split()
            console_width = int(console_width)

    except:
        # if we cant get the console width
        console_width = 80

    with torch.no_grad():
        for batch in validation_ds:
            count += 1
            encoder_input = batch['encoder_input'].to(device) # [B, seq_len]
            encoder_mask = batch['encoder_mask'].to(device) # [B, 1, 1, seq_len]

            ## check that the batch size is 1
            assert encoder_input.size(0) == 1, "batch size must be 1 for validation"

            model_out = greedy_decode(model, encoder_input, encoder_mask, tokenizer_src, tokenizer_tgt, max_len, device)

            source_text = batch["src_text"][0]
            target_text = batch["tgt_text"][0]
            model_out_text = tokenizer_tgt.decode(model_out.detach().cpu().numpy())

            source_texts.append(source_text)
            expected.append(target_text)
            predicted.append(model_out_text)

            ## print the sourc , target and model output

            print_msg('-'* console_width)
            print_msg(f"{f'SOURCE: ':>12}{source_text}")
            print_msg(f"{f'TARGET: ':>12}{target_text}")
            print_msg(f"{f'PREDICTED: ':>12}{model_out_text}")

            if count == num_examples:
                print_msg('-'*console_width)
                break
    if writer:
        ## evaluate the character error rate
        ## compute the char error rate
        metric = torchmetrics.CharErrorRate()
        cer = metric(predicted, expected)
        writer.add_scalar('validation_cer', cer, global_step)
        writer.flush()

        ## compute word error rate
        metric = torchmetrics.WordErrorRate()
        wer = metric(predicted, expected)
        writer.add_scalar('validation_wer', wer, global_step)
        writer.flush()

        ## compute the BLEU metric
        metric = torchmetrics.BLEUScore()
        bleu = metric(predicted, expected)
        writer.add_scalar('validation BLEU', bleu, global_step)
        writer.flush()

def get_all_sentences(ds, lang):
    for item in ds:
        yield item['translation'][lang]

def get_or_build_tokenizer(config, ds, lang):
    tokenizer_path = Path(config['tokenizer_file'].format(lang))
    if not Path.exists(tokenizer_path):
        ## most code taken from  https://huggingface.co/docs/tokenizers/quicktour
        tokenizer = Tokenizer(WordLevel(unk_token = "[UNK]"))
        tokenizer.pre_tokenizer = Whitespace()
        trainer = WordLevelTrainer(special_tokens=["[UNK]","[PAD]","[SOS]","[EOS]"], min_frequency = 2)
        ## for a word to be a part of our dataset, it should atleast come twice otherwise its not the part of our dataset
        tokenizer.train_from_iterator(get_all_sentences(ds, lang), trainer = trainer)
        tokenizer.save(str(tokenizer_path))
    else:
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
    return tokenizer

def get_ds(config):
    # it has only the train split, so we divide it ourselves
    ds_raw = load_dataset('opus_books', f"{config['lang_src']}-{config['lang_tgt']}", split = 'train')
    print("dataset_size" , len(ds_raw))

    # build tokenizers
    tokenizer_src = get_or_build_tokenizer(config, ds_raw, config['lang_src'])
    tokenizer_tgt = get_or_build_tokenizer(config, ds_raw, config['lang_tgt'])




    ## keep 90% for traning and 10% for validation
    train_ds_size = int(0.9 * len(ds_raw))
    val_ds_size = len(ds_raw) - train_ds_size

    train_ds_raw, val_ds_raw = random_split(ds_raw, [train_ds_size, val_ds_size])
    sorted_train_ds = sorted(train_ds_raw, key = lambda x:len(x["translation"][config['lang_src']]))
    # sorted_train_ds = train_ds_raw ## not sorted, taken as it is
    filtered_sorted_train_ds = [k for k in sorted_train_ds if (len(k['translation'][config['lang_src']]) < 150 and  len(k['translation'][config['lang_src']]) > 3)]
    filtered_sorted_train_ds = [k for k in filtered_sorted_train_ds if (len(k['translation'][config['lang_tgt']]) < 150 and len(k['translation'][config['lang_tgt']]) > 3)]
    filtered_sorted_train_ds = [k for k in filtered_sorted_train_ds if len(k['translation'][config['lang_src']]) + 10 > len(k['translation'][config['lang_tgt']]) ]


    train_ds = BillingualDataset(filtered_sorted_train_ds, tokenizer_src, tokenizer_tgt, config['lang_src'], config['lang_tgt'], config['seq_len'])
    # train_ds = BillingualDataset(train_ds_raw, tokenizer_src, tokenizer_tgt, config['lang_src'], config['lang_tgt'], config['seq_len'])
    val_ds = BillingualDataset(val_ds_raw, tokenizer_src, tokenizer_tgt, config['lang_src'], config['lang_tgt'], config['seq_len'])


    # find max length of each sentence in the source and target sentence
    max_len_src = 0
    max_len_tgt = 0

    for item in ds_raw:
        src_ids = tokenizer_src.encode(item['translation'][config['lang_src']]).ids
        tgt_ids = tokenizer_tgt.encode(item['translation'][config['lang_tgt']]).ids
        max_len_src = max(max_len_src, len(src_ids))
        max_len_tgt = max(max_len_tgt, len(tgt_ids))


    max_len_src_filtered = 0
    max_len_tgt_filtered = 0
    for item in filtered_sorted_train_ds:
        src_ids = tokenizer_src.encode(item['translation'][config['lang_src']]).ids
        tgt_ids = tokenizer_tgt.encode(item['translation'][config['lang_tgt']]).ids
        max_len_src_filtered = max(max_len_src_filtered, len(src_ids))
        max_len_tgt_filtered = max(max_len_tgt_filtered, len(tgt_ids))


    print(f'Max length of source sentence: {max_len_src}')
    print(f'Max length of target sentence: {max_len_tgt}')

    print(f'Max length of filtered source sentence: {max_len_src_filtered}')
    print(f'Max length of filterd target sentence: {max_len_tgt_filtered}')

    print("length of train dataset" , len(train_ds))
    print("length of validation dataset" , len(val_ds))

    train_dataloader = DataLoader(train_ds, batch_size = config['batch_size'], shuffle = True, collate_fn = collate_fn )
    val_dataloader = DataLoader(val_ds, batch_size = 1, shuffle = True)

    return train_dataloader, val_dataloader, tokenizer_src, tokenizer_tgt



def collate_fn(batch):
    encoder_input_max = max(b['encoder_str_length'] for b in batch)
    decoder_input_max = max(b['decoder_str_length'] for b in batch)
    encoder_input_max += 2
    decoder_input_max += 2

    # input_size_max = max(encoder_input_max, decoder_input_max)

    pad_token_encoder = torch.tensor([tokenizer_src.token_to_id("[PAD]")], dtype = torch.int64)
    pad_token_decoder = torch.tensor([tokenizer_tgt.token_to_id("[PAD]")], dtype = torch.int64)

    encoder_inputs = []
    decoder_inputs = []
    encoder_masks = []
    decoder_masks = []
    labels = []
    src_texts = []
    tgt_texts = []

    for b in batch:
        enc_num_padding_token = encoder_input_max - len(b['encoder_input'])
        dec_num_padding_token = decoder_input_max - len(b['decoder_input'])
        label_num_padding_token = decoder_input_max - len(b['label'])

        encoder_input = torch.cat(
            [
                b['encoder_input'],
                torch.tensor([pad_token_encoder] * enc_num_padding_token , dtype = torch.int64)
            ],
            dim = 0,
        )
        decoder_input = torch.cat(
            [
                b['decoder_input'],
                torch.tensor([pad_token_decoder] * dec_num_padding_token, dtype = torch.int64)
            ],
            dim = 0,
        )
        label = torch.cat(
            [
                b['label'],
                torch.tensor([pad_token_decoder] * label_num_padding_token, dtype = torch.int64)
            ],
            dim = 0,
        )
        encoder_mask = (encoder_input != pad_token_encoder).unsqueeze(0).unsqueeze(0).int()
        decoder_mask = (decoder_input != pad_token_decoder).unsqueeze(0).int() & causal_mask(decoder_input_max)
        encoder_inputs.append(encoder_input)
        decoder_inputs.append(decoder_input)
        encoder_masks.append(encoder_mask)
        decoder_masks.append(decoder_mask)
        labels.append(label)
        src_texts.append(b["src_text"])
        tgt_texts.append(b['tgt_text'])

    # print(k.size() for k in encoder_inputs)
    # print(k.shape() for k in decoder_inputs)
    # print(k.shape() for k in encoder_masks)
    # print(k.shape() for k in decoder_masks)

    return {
        "encoder_input": torch.vstack(encoder_inputs),
        "decoder_input": torch.vstack(decoder_inputs),
        "encoder_mask": torch.vstack(encoder_masks),
        "decoder_mask": torch.vstack(decoder_masks),
        "label" : torch.vstack(labels),
        "src_text" : src_texts,
        "tgt_text": tgt_texts
    }


def get_model(config, vocab_src_len, vocab_tgt_len):
    model = build_transformer(vocab_src_len, vocab_tgt_len, config['seq_len'], config['seq_len'], d_model = config['d_model'])
    return model

# from config import get_config

cfg = get_config()
cfg['batch_size'] = 8
cfg['preload'] = None
cfg['num_epochs'] = 10

# from train import train_model

torch.cuda.amp.autocast(enabled=True)
## in pytorch lightening, check if the above command is already enabled when precision is set to FP16

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device: ", device)

## make sure the weights folder exists
Path(cfg['model_folder']).mkdir(parents = True, exist_ok = True)

train_dataloader, val_dataloader, tokenizer_src, tokenizer_tgt = get_ds(cfg)


model = get_model(cfg, tokenizer_src.get_vocab_size(), tokenizer_tgt.get_vocab_size()).to(device)

# tensorboard
writer = SummaryWriter(cfg['experiment_name'])

optimizer = torch.optim.Adam(model.parameters(), lr = cfg['lr'] , eps = 1e-9)
## each feature can have different learnign rate, so for words seen less it can increase learning rate of those weights

def get_lr(optimizer):
    for param_group in optimizer.param_groups:
        return param_group['lr']

MAX_LR = 10**-3
STEPS_PER_EPOCH = len(train_dataloader)
EPOCHS = 30

# Scheduler
scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer,
                                                max_lr = MAX_LR,
                                                steps_per_epoch = STEPS_PER_EPOCH,
                                                epochs = EPOCHS,
                                                pct_start = 1/10 if EPOCHS != 1 else 0.5,
                                                div_factor = 10,
                                                three_phase = True,
                                                final_div_factor = 10,
                                                anneal_strategy = "linear"
                                                )

## if the user has specified a model to preload before training , load it
initial_epoch = 0
global_step = 0
# if config['preload']:
#     model_filename = get_weights_file_path(config, config['preload'])
#     print(f'Preloading model {model_filename}')
#     state = torch.load(model_filename)
#     model.load_state_dict(state['model_state_dict'])
#     initial_epoch = state['epoch'] + 1
#     optimizer.load_state_dict(state['optimizer_state_dict'])       ## important to store optimiser for Adam as all weights have different lr
#     global_step = state['global_step']
#     print("preloaded")

loss_fn = nn.CrossEntropyLoss(ignore_index = tokenizer_src.token_to_id('[PAD]'), label_smoothing= 0.1)

scaler = torch.cuda.amp.GradScaler()
lr = [0.0]

for epoch in range(initial_epoch, EPOCHS):
    loss_acc = []

    model.train()
    batch_iterator = tqdm(train_dataloader, desc = f"Processing Epoch {epoch:02d}")

    for batch in batch_iterator:
        torch.cuda.empty_cache()

        encoder_input = batch['encoder_input'].to(device) # [B, seq_len]
        decoder_input = batch['decoder_input'].to(device) # [B, seq_len]
        encoder_mask = batch['encoder_mask'].to(device) # [B, 1, 1, Seq_len]
        decoder_mask = batch['decoder_mask'].to(device) # [B, 1, Seq_len, Seq_len]

        ## run the tensors through the encoder, decoder and projection layer
        # print(encoder_input.shape)
        # print(decoder_mask.shape)
        encoder_mask = encoder_mask.unsqueeze(1)
        decoder_mask = decoder_mask.unsqueeze(1)
        # print(encoder_mask.shape)

        with torch.autocast(device_type = 'cuda', dtype = torch.float16 ):
            encoder_output = model.encode(encoder_input, encoder_mask)  # [B, seq_len, d_model]
            decoder_output = model.decode(encoder_output, encoder_mask, decoder_input, decoder_mask)
            proj_output = model.project(decoder_output) # [B, seq_len, Vocab_size]

            ## compare the ouput with the label
            label = batch['label'].to(device) ## [B, seq_len]

            ## compute the loss using simple cross entropy
            loss = loss_fn(proj_output.view(-1, tokenizer_tgt.get_vocab_size()), label.view(-1))
            loss_acc.append(loss)
            batch_iterator.set_postfix(
                {"loss_acc": f"{torch.mean(torch.stack(loss_acc)).item():6.3f}",
                    "loss": f"{loss.item():6.3f}", "lr" : f"{get_lr(optimizer)}"
                })



        ## log the loss
        writer.add_scalar('train_loss', loss.item(), global_step)
        writer.flush()

        ## backpropagate the loss
        # loss.backward()
        scaler.scale(loss).backward()

        ## update the weights
        # optimizer.step()
        scale = scaler.get_scale()
        scaler.step(optimizer)
        scaler.update()
        skip_lr_sched = (scale > scaler.get_scale())
        if not skip_lr_sched:
            scheduler.step()
        lr.append(scheduler.get_last_lr())
        optimizer.zero_grad(set_to_none = True)

        global_step += 1


    ## run validation at the end of every epoch
    run_validation(model,val_dataloader, tokenizer_src, tokenizer_tgt, cfg['seq_len'], device, lambda msg : batch_iterator.write(msg) , global_step, writer)

    ## remove the prev model files
    if epoch > 0:
        prev_model_filename  = get_weights_file_path(cfg, f"{epoch - 1:02d}")
        os.remove(prev_model_filename)

    model_filename = get_weights_file_path(cfg, f"{epoch:02d}")
    torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'global_step': global_step
    }, model_filename )

source_lang = "en"
target_lang = "hi"

input_text = "My name is Ramnarayan and I am a data scientist in google "

# Tokenize input text
tokenized = tokenizer([input_text], return_tensors='np')

# Generate translation
out = model.generate(**tokenized, max_length=128)
print(out)

# Decode generated output
with tokenizer.as_target_tokenizer():
    print(tokenizer.decode(out[0], skip_special_tokens=True))