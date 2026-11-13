---
datasets:
- minishlab/tokenlearn-c4-multilingual-bge-m3
language:
- en
- multilingual
- af
- am
- ar
- az
- be
- bg
- bn
- ca
- ceb
- co
- cs
- cy
- da
- de
- el
- eo
- es
- et
- eu
- fa
- fi
- fil
- fr
- fy
- ga
- gd
- gl
- gu
- ha
- haw
- hi
- hmn
- ht
- hu
- hy
- id
- ig
- is
- it
- iw
- ja
- jv
- ka
- kk
- km
- kn
- ko
- ku
- ky
- la
- lb
- lo
- lt
- lv
- mg
- mi
- mk
- ml
- mn
- mr
- ms
- mt
- my
- ne
- nl
- 'no'
- ny
- pa
- pl
- ps
- pt
- ro
- ru
- sd
- si
- sk
- sl
- sm
- sn
- so
- sq
- sr
- st
- su
- sv
- sw
- ta
- te
- tg
- th
- tr
- uk
- ur
- uz
- vi
- xh
- yi
- yo
- zh
- zu
library_name: model2vec
license: mit
model_name: potion-multilingual-128M
tags:
- embeddings
- static-embeddings
- sentence-transformers
---

# potion-multilingual-128M Model Card

<div align="center">
  <img width="35%" alt="Model2Vec logo" src="https://raw.githubusercontent.com/MinishLab/model2vec/main/assets/images/logo_v2.png">
</div>


This [Model2Vec](https://github.com/MinishLab/model2vec) model is pre-trained using [Tokenlearn](https://github.com/MinishLab/tokenlearn) on all languages in the [C4 dataset](https://huggingface.co/datasets/allenai/c4). It is a distilled version of the [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) Sentence Transformer. It uses static embeddings, allowing text embeddings to be computed orders of magnitude faster on both GPU and CPU. It is designed for applications where computational resources are limited or where real-time performance is critical.

potion-multilingual-128M is a multilingual model, trained on 101 languages, and is capable of generating embeddings for any text in any language. The model produces 256 dimensional embeddings, and has a theoretically unlimited context length since embeddings are static (pre-computed).


## Installation

Install model2vec using pip:
```
pip install model2vec
```

## Usage

### Using Model2Vec

The [Model2Vec library](https://github.com/MinishLab/model2vec) is the fastest and most lightweight way to run Model2Vec models.

Load this model using the `from_pretrained` method:
```python
from model2vec import StaticModel

# Load a pretrained Model2Vec model
model = StaticModel.from_pretrained("minishlab/potion-multilingual-128M")

# Compute text embeddings
embeddings = model.encode(["Example sentence"])
```

## How it works

Model2vec creates a small, static model that outperforms other static embedding models by a large margin on all tasks on MTEB. This model is pre-trained using Tokenlearn. It's created using the following steps:

- Distillation: first, a model is distilled from a sentence transformer model using Model2Vec.
- Training data creation: the sentence transformer model is used to create training data by creating mean output embeddings on a large corpus. In this case, 2 million sentences from the C4 dataset were used from 101 different languages, sampled using temperature-smoothed sampling proportional to the language size.
- Training: the distilled model is trained on the training data using Tokenlearn.

The results for this model can be found on the [Model2Vec results page](https://github.com/MinishLab/model2vec/blob/main/results/README.md).


## Results

| Model | Mean (Task) | Mean (TaskType) | BitMining | Class | Clust | InstRet | MultiClass | PairClass | Rank | Ret | STS |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [LaBSE](https://huggingface.co/sentence-transformers/LaBSE) | 52.07 | 45.65 | 76.35 | 54.60 | 38.08 | -3.00 | 20.12 | 75.97 | 50.20 | 33.17 | 65.35 |
| **[potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128M)** | **47.31** | **40.40** | **40.72** | **52.36** | **38.80** | **-2.08** | **15.95** | **71.39** | **47.39** | **37.86** | **61.23** |
| [static-similarity-mrl-multilingual-v1](https://huggingface.co/sentence-transformers/static-similarity-mrl-multilingual-v1) | 47.24 | 41.38 | 50.62 | 48.60 | 30.67 | -1.24 | 14.74 | 74.34 | 49.45 | 41.21 | 64.02 |
| [M2V_multilingual_output](https://huggingface.co/minishlab/M2V_multilingual_output) | 42.13 | 35.89 | 36.88 | 49.75 | 30.09 | -0.07 | 14.34 | 69.74 | 41.51 | 25.42 | 55.33 |

The results show that **potion-multilingual-128M** is the most performant static multilingual model, reaching 90.86% of the performance of [LaBSE](https://huggingface.co/sentence-transformers/LaBSE) with a mean task score of 47.31 while being orders of magnitude faster.

For full results, see the [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard).

## Additional Resources

- [All Model2Vec models on the hub](https://huggingface.co/models?library=model2vec)
- [Model2Vec Repo](https://github.com/MinishLab/model2vec)
- [Tokenlearn repo](https://github.com/MinishLab/tokenlearn)
- [Model2Vec Results](https://github.com/MinishLab/model2vec/blob/main/results/README.md)
- [Model2Vec Tutorials](https://github.com/MinishLab/model2vec/tree/main/tutorials)


## Library Authors

Model2Vec was developed by the [Minish Lab](https://github.com/MinishLab) team consisting of [Stephan Tulkens](https://github.com/stephantul) and [Thomas van Dongen](https://github.com/Pringled).

## Citation

If you use Model2Vec in your research, please cite the following:

```bibtex
@software{minishlab2024model2vec,
  author       = {Stephan Tulkens and {van Dongen}, Thomas},
  title        = {Model2Vec: Fast State-of-the-Art Static Embeddings},
  year         = {2024},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.17270888},
  url          = {https://github.com/MinishLab/model2vec},
  license      = {MIT}
}
```