# BERT
Code and Swedish pre-trained models for BERT.

## What is BERT?

BERT is a method of pre-training language representations, meaning that we train
a general-purpose "language understanding" model on a large text corpus (like
Wikipedia), and then use that model for downstream NLP tasks that we care about
(like question answering). BERT outperforms previous methods because it is the
first *unsupervised*, *deeply bidirectional* system for pre-training NLP.

*Unsupervised* means that BERT was trained using only a plain text corpus, which
is important because an enormous amount of plain text data is publicly available
on the web in many languages.

We used Swedish Wikipedia with approximatelly 2 million articles and 300 million words.

The links to the models are here (right-click, 'Save link as...' on the name):

*   **[`Swedish BERT-Base, Uncased`](https://storage.googleapis.com/ai-center/2019_06_15/swe-uncased_L-12_H-768_A-12.zip)**:
    12-layer, 768-hidden, 12-heads, 110M parameters
*   **[`Swedish BERT-Large, Uncased`](https://storage.googleapis.com/ai-center/2019_06_15/swe-uncased_L-24_H-1024_A-16.zip)**:
    24-layer, 1024-hidden, 16-heads, 340M parameters

