import torch
from torch import nn
import math

class InputEmbeddings(nn.Module):
    def __init__(self,d_model: int,vocab_size: int):
        super().__init__()
        self.d_model=d_model
        self.vocab_size=vocab_size


        #vocab_size: The size of the vocabulary used
        self.embedding=nn.Embedding(vocab_size,d_model)

    def forward(self, x):
        #x: the id/position of the word in the vocabulary
        return self.embedding(x) * math.sqrt(self.d_model)


class PositionalEncoding(nn.Module):
    def __init__(self,d_model: int,seq_len: int,dropout: float):
        super().__init__()
        self.d_model=d_model
        self.seq_len=seq_len
        self.dropout=nn.Dropout(p=dropout)

        pe=torch.zeros(seq_len,d_model)

        # Makes a variable with shape (seq_len,1)
        pos=torch.arange(0,seq_len,dtype=torch.float).unsqueeze(1)

        # Makes a variable with shape d_model/2 [d_model/2 because even position or odd poisitons are basically of total positions]
        div_term=torch.exp(torch.arange(0,self.d_model,2).float()*(-math.log(10000.0)/self.d_model))
        
        pe[:,0::2]=torch.sin(pos*div_term)
        pe[:,1::2]=torch.cos(pos*div_term)

        pe=pe.unsqueeze(0)

        self.register_buffer('pe',pe)

    def forward(self,x):
        x=x+(self.pe[:,:x.shape[1],:]).requires_grad_(False)
        print(self.pe[:,:x.shape[1],:].shape)
        return self.dropout(x)


class LayerNormalization(nn.Module):
    def __init__(self,eps: float=1e-6):
        super().__init__()
        self.eps=eps
        self.alpha=nn.Parameter(torch.ones(1))
        self.bias=nn.Parameter(torch.zeros(1))

    def forward(self,x):
        mean=x.mean(dim=-1,keepdim=True)
        std=x.std(dim=-1,keepdim=True)
        return (self.alpha*(x-mean)/(std+self.eps))+self.bias


class FeedForwardBlock(nn.Module):
    def __init__(self,d_model: int, d_ff: int,dropout:float):
        super().__init__()
        self.linear_1=nn.Linear(d_model,d_ff)
        self.dropout=nn.dropout(dropout)
        self.linear_2=nn.Linear(d_ff,d_model)

    def forward(self,x):
        return self.linear_2(self.dropout(self.linear_1(x)))


class MultiHeadAttentionBlock(nn.Module):

    def __init__(self,d_model: int,h: int,dropout: float):
        super().__init__()
        self.d_model=d_model
        self.h=h
        self.dropout=nn.Dropout(p=self.dropout)
        assert d_model%h==0, f"{d_model} is not divisible by {h}"

        self.d_k=d_model//h
        self.w_q=nn.Linear(d_model,d_model) #Wq
        self.w_k=nn.Linear(d_model,d_model) #Wk
        self.w_v=nn.Linear(d_model,d_model) #Wv

        self.w_o=nn.Linear(d_model,d_model) #Wo

    @staticmethod
    def attention(query, key, value, mask, dropout: nn.Dropout):
        d_k=query.shape[-1]

        attention_scores=(query@key.transpose(-2,-1))/math.sqrt(d_k)
        if(mask is not None):
            attention_scores.masked_fill_(mask==0,-1e9)
        attention_scores=attention_scores.softmax(dim=-1)
        if(dropout is not None):
            attention_scores=dropout(attention_scores)

        return (attention_scores@value), attention_scores

    def forward(self,q,k,v,mask):
        query=self.w_q(q) # (Batch, seq_len, d_model) --> (Batch, seq_len, d_model)
        key=self.w_k(k) # (Batch, seq_len, d_model) --> (Batch, seq_len, d_model)
        value=self.w_v(v) # (Batch, seq_len, d_model) --> (Batch, seq_len, d_model)

        # (Batch, seq_len, d_model) --> (Batch, seq_len, h, d_model) --> (Batch, h , seq_len, d_k)

        query=query.view(query.shape[0],query.shape[1],self.h,self.d_k).transpose(1,2)
        key=query.view(query.shape[0],query.shape[1],self.h,self.d_k).transpose(1,2)
        value=query.view(query.shape[0],query.shape[1],self.h,self.d_k).transpose(1,2)

        x, self.attention_scores=MultiHeadAttentionBlock.attention(query, key, value, mask, self.dropout)

        # (Batch, h, seq_len, d_k) --> (Batch, seq_len, h, d_k) --> (Batch, seq_len, d_model)
        x=x.transpose(1,2).contiguous().view(x.shape[0],-1,self.h*self.d_k)

        # (Batch, seq_len, d_model) --> (Batch, seq_len, d_model)
        return self.w_o(x)

class ResidualConnection(nn.Module):
    def __init__(self, dropout: float):
        super().__init__()
        self.dropout=nn.Dropout(dropout)
        self.norm=LayerNormalization()

    def forward(self,x,sublayer):
        return x+self.dropout(sublayer(self.norm(x)))
        

class EncoderBlock(nn.Module):
    def __init__(self,self_attention_block: MultiHeadAttentionBlock, feed_forward_block: FeedForwardBlock, dropout:float):
        super().__init__()
        self.self_attention_block=self_attention_block
        self.feed_forward_block=feed_forward_block
        self.residual_connections=nn.ModuleList([ResidualConnection(dropout) for _ in range(2)])

    def forward(self,x,src_mask):
        x=self.residual_connections[0](x,lambda x: self.self_attention_block(x,x,x,src_mask))
        x=self.residual_connections[1](x,lambda x: self.feed_forward_block(x))                                    ############ HERE
        return x


class Encoder(nn.Module):
    def __init__(self,layers: nn.ModuleList):
        super().__init__()
        self.layers=layers
        self.norm=LayerNormalization()

    def forward(self, x, mask):
        for layer in self.layers:
            x=layer(x,mask)
        return self.norm(x)

class DecoderBlock(nn.Module):
    def __init__(self,self_attention_block: MultiHeadAttentionBlock, cross_attention_block: MultiHeadAttentionBlock, feed_forward_block: FeedForwardBlock, dropout: float):
        super().__init__()
        self.self_attention_block=self_attention_block
        self.cross_attention_block=cross_attention_block
        self.feed_forward_block=feed_forward_block
        self.residual_connections=nn.ModuleList([ResidualConnection(dropout) for _ in range(3)])              ############## HERE

    def forward(self, x, encoder_output, src_mask, tgt_mask):
        x=self.residual_connections[0](x,lambda x: self.self_attention_block(x,x,x,tgt_mask))
        x=self.residual_connections[1](x, lambda x: self.cross_attention_block(x,encoder_output,encoder_output,src_mask))
        x=self.residual_connections[2](x, lambda x: self.feed_forward_block(x))

        return x


class Decoder(nn.Module):
    def __init__(self,layers: nn.ModuleList):
        super().__init__()
        self.layers=layers
        self.norm=LayerNormalization()

    def forward(self,x,encoder_output,src_mask,tgt_mask):
        for layer in self.layers:
            x=layer(x,encoder_output,src_mask,tgt_mask)

        return self.norm(x)

class ProjectionLayer(nn.Module):

    def __init__(self, d_model, vocab_size) -> None:
        super().__init__()
        self.proj = nn.Linear(d_model, vocab_size)

    def forward(self, x) -> None:
        # (batch, seq_len, d_model) --> (batch, seq_len, vocab_size)
        return self.proj(x)
    
class Transformer(nn.Module):

    def __init__(self, encoder: Encoder, decoder: Decoder, src_embed: InputEmbeddings, tgt_embed: InputEmbeddings, src_pos: PositionalEncoding, tgt_pos: PositionalEncoding, projection_layer: ProjectionLayer) -> None:
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.src_pos = src_pos
        self.tgt_pos = tgt_pos
        self.projection_layer = projection_layer

    def encode(self, src, src_mask):
        # (batch, seq_len, d_model)
        src = self.src_embed(src)
        src = self.src_pos(src)
        return self.encoder(src, src_mask)
    
    def decode(self, encoder_output: torch.Tensor, src_mask: torch.Tensor, tgt: torch.Tensor, tgt_mask: torch.Tensor):
        # (batch, seq_len, d_model)
        tgt = self.tgt_embed(tgt)
        tgt = self.tgt_pos(tgt)
        return self.decoder(tgt, encoder_output, src_mask, tgt_mask)
    
    def project(self, x):
        # (batch, seq_len, vocab_size)
        return self.projection_layer(x)
    
def build_transformer(src_vocab_size: int, tgt_vocab_size: int, src_seq_len: int, tgt_seq_len: int, d_model: int=512, N: int=6, h: int=8, dropout: float=0.1, d_ff: int=2048) -> Transformer:
    # Create the embedding layers
    src_embed = InputEmbeddings(d_model, src_vocab_size)
    tgt_embed = InputEmbeddings(d_model, tgt_vocab_size)

    # Create the positional encoding layers
    src_pos = PositionalEncoding(d_model, src_seq_len, dropout)
    tgt_pos = PositionalEncoding(d_model, tgt_seq_len, dropout)
    
    # Create the encoder blocks
    encoder_blocks = []
    for _ in range(N):
        encoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        encoder_block = EncoderBlock(d_model, encoder_self_attention_block, feed_forward_block, dropout)
        encoder_blocks.append(encoder_block)

    # Create the decoder blocks
    decoder_blocks = []
    for _ in range(N):
        decoder_self_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        decoder_cross_attention_block = MultiHeadAttentionBlock(d_model, h, dropout)
        feed_forward_block = FeedForwardBlock(d_model, d_ff, dropout)
        decoder_block = DecoderBlock(d_model, decoder_self_attention_block, decoder_cross_attention_block, feed_forward_block, dropout)
        decoder_blocks.append(decoder_block)
    
    # Create the encoder and decoder
    encoder = Encoder(d_model, nn.ModuleList(encoder_blocks))
    decoder = Decoder(d_model, nn.ModuleList(decoder_blocks))
    
    # Create the projection layer
    projection_layer = ProjectionLayer(d_model, tgt_vocab_size)
    
    # Create the transformer
    transformer = Transformer(encoder, decoder, src_embed, tgt_embed, src_pos, tgt_pos, projection_layer)
    
    # Initialize the parameters
    for p in transformer.parameters():
        if p.dim() > 1:
            nn.init.xavier_uniform_(p)
    
    return transformer
