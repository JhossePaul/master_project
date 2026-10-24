"""Modelo de sentimiento diminuto y aleatorio, construido sin red."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tiny_weights(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Carpeta con un RoBERTa de 2 capas y un tokenizador de palabras."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")

    words = (
        "la app no abre mala buena excelente pésima me cobraron doble "
        "pero gracias emoji cara cabreada url @usuario jaja"
    ).split()
    vocab = {"<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3}
    vocab.update({w: i + 4 for i, w in enumerate(words)})
    # Tokens especiales del vocabulario, no credenciales (falso positivo S106).
    special = {
        "bos_token": "<s>",
        "eos_token": "</s>",
        "unk_token": "<unk>",
        "pad_token": "<pad>",
    }
    core = tokenizers.Tokenizer(
        tokenizers.models.WordLevel(vocab, special["unk_token"])
    )
    core.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    core.post_processor = tokenizers.processors.TemplateProcessing(
        single="<s> $A </s>", special_tokens=[("<s>", 0), ("</s>", 2)]
    )
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=core, **special
    )
    torch.manual_seed(0)
    config = transformers.RobertaConfig(
        vocab_size=len(vocab),
        hidden_size=16,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=32,
        max_position_embeddings=130,
        pad_token_id=1,
        num_labels=3,
        id2label={0: "NEG", 1: "NEU", 2: "POS"},
        label2id={"NEG": 0, "NEU": 1, "POS": 2},
    )
    model = transformers.RobertaForSequenceClassification(config).half()
    path = tmp_path_factory.mktemp("weights")
    model.save_pretrained(path)
    tokenizer.save_pretrained(path)
    return path
