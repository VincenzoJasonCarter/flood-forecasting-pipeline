"""PyTorch model architectures — must stay identical to the ones used during
training since weights are loaded via state_dict.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Hyperparameter TFT (harus sama persis dengan yang dipakai saat training)
TFT_HIDDEN = 64
TFT_HEADS = 4
TFT_DROPOUT = 0.2
TFT_LSTM_LAYERS = 1


class LSTMForecaster(nn.Module):
    def __init__(self, n_features, hidden_size=128, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


class GRUForecaster(nn.Module):
    def __init__(self, n_features, hidden_size=128, num_layers=2, dropout=0.2):
        super().__init__()
        self.gru = nn.GRU(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        out, _ = self.gru(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


class GatedLinearUnit(nn.Module):
    """GLU: mengatur seberapa besar informasi diteruskan (gating)."""

    def __init__(self, input_size, hidden_size=None, dropout=0.1):
        super().__init__()
        hidden_size = hidden_size or input_size
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(input_size, hidden_size * 2)
        self.hidden_size = hidden_size

    def forward(self, x):
        x = self.dropout(x)
        x = self.fc(x)
        return F.glu(x, dim=-1)


class GatedResidualNetwork(nn.Module):
    """GRN(x) = LayerNorm(x + GLU(ELU(W1 x + b1) -> W2))."""

    def __init__(self, input_size, hidden_size, output_size=None, dropout=0.1,
                 context_size=None):
        super().__init__()
        output_size = output_size or input_size
        self.input_size = input_size
        self.output_size = output_size

        self.fc1 = nn.Linear(input_size, hidden_size)
        self.context = (nn.Linear(context_size, hidden_size, bias=False)
                         if context_size is not None else None)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.glu = GatedLinearUnit(hidden_size, output_size, dropout)
        self.layer_norm = nn.LayerNorm(output_size)

        self.skip = (nn.Linear(input_size, output_size)
                     if input_size != output_size else None)

    def forward(self, x, context=None):
        residual = x if self.skip is None else self.skip(x)
        h = self.fc1(x)
        if self.context is not None and context is not None:
            h = h + self.context(context)
        h = F.elu(h)
        h = self.fc2(h)
        h = self.glu(h)
        return self.layer_norm(h + residual)


class VariableSelectionNetwork(nn.Module):
    def __init__(self, n_features, hidden_size, dropout=0.1):
        super().__init__()
        self.n_features = n_features
        self.hidden_size = hidden_size

        self.flattened_grn = GatedResidualNetwork(
            n_features, hidden_size, n_features, dropout
        )
        self.per_feature_grn = nn.ModuleList([
            GatedResidualNetwork(1, hidden_size, hidden_size, dropout)
            for _ in range(n_features)
        ])

    def forward(self, x):
        weights = self.flattened_grn(x)
        weights = torch.softmax(weights, dim=-1).unsqueeze(-1)

        transformed = torch.stack([
            self.per_feature_grn[i](x[..., i:i + 1])
            for i in range(self.n_features)
        ], dim=-2)

        combined = (transformed * weights).sum(dim=-2)
        return combined, weights.squeeze(-1)


class InterpretableMultiHeadAttention(nn.Module):
    def __init__(self, hidden_size, n_heads, dropout=0.1):
        super().__init__()
        assert hidden_size % n_heads == 0
        self.n_heads = n_heads
        self.d_head = hidden_size // n_heads

        self.q = nn.Linear(hidden_size, hidden_size)
        self.k = nn.Linear(hidden_size, hidden_size)
        self.v = nn.Linear(hidden_size, self.d_head)
        self.out = nn.Linear(self.d_head, hidden_size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        B, T, _ = x.shape
        q = self.q(x).view(B, T, self.n_heads, self.d_head).transpose(1, 2)
        k = self.k(x).view(B, T, self.n_heads, self.d_head).transpose(1, 2)
        v = self.v(x).unsqueeze(1)

        scores = (q @ k.transpose(-2, -1)) / (self.d_head ** 0.5)
        attn = torch.softmax(scores, dim=-1)
        attn = self.dropout(attn)

        ctx = attn @ v
        ctx = ctx.mean(dim=1)
        return self.out(ctx), attn


class TFTForecaster(nn.Module):
    """Temporal Fusion Transformer untuk direct single-step forecasting."""

    def __init__(self, n_features, hidden_size=64, n_heads=4,
                 dropout=0.2, lstm_layers=1):
        super().__init__()
        self.vsn = VariableSelectionNetwork(n_features, hidden_size, dropout)

        self.lstm_encoder = nn.LSTM(
            input_size=hidden_size, hidden_size=hidden_size,
            num_layers=lstm_layers, batch_first=True,
            dropout=dropout if lstm_layers > 1 else 0.0,
        )
        self.post_lstm_glu = GatedLinearUnit(hidden_size, hidden_size, dropout)
        self.post_lstm_norm = nn.LayerNorm(hidden_size)

        self.enrichment = GatedResidualNetwork(
            hidden_size, hidden_size, hidden_size, dropout,
            context_size=hidden_size,
        )
        self.attention = InterpretableMultiHeadAttention(
            hidden_size, n_heads, dropout
        )
        self.post_attn_glu = GatedLinearUnit(hidden_size, hidden_size, dropout)
        self.post_attn_norm = nn.LayerNorm(hidden_size)

        self.position_wise = GatedResidualNetwork(
            hidden_size, hidden_size, hidden_size, dropout
        )
        self.head = nn.Linear(hidden_size, 1)

    def forward(self, x, return_weights=False):
        selected, var_weights = self.vsn(x)

        lstm_out, (h_n, _) = self.lstm_encoder(selected)
        lstm_out = self.post_lstm_norm(
            self.post_lstm_glu(lstm_out) + selected
        )

        context = h_n[-1].unsqueeze(1).expand(-1, lstm_out.size(1), -1)
        enriched = self.enrichment(lstm_out, context)

        attn_out, attn_weights = self.attention(enriched)
        attn_out = self.post_attn_norm(
            self.post_attn_glu(attn_out) + enriched
        )

        out = self.position_wise(attn_out)
        pred = self.head(out[:, -1, :]).squeeze(-1)

        if return_weights:
            return pred, var_weights, attn_weights
        return pred


TORCH_ARCHITECTURES = {
    "lstm": lambda n_features: LSTMForecaster(n_features=n_features),
    "gru": lambda n_features: GRUForecaster(n_features=n_features),
    "tft": lambda n_features: TFTForecaster(
        n_features=n_features, hidden_size=TFT_HIDDEN, n_heads=TFT_HEADS,
        dropout=TFT_DROPOUT, lstm_layers=TFT_LSTM_LAYERS,
    ),
}
