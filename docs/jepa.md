# System Architecture Design: JEPA-Based Expert Retrieval & Recommendation System
**Target Scale:** 150,000 Scientists
**Core Objective:** Extract and rank scientists based on semantic research topics and track scientific trajectories using a Joint-Embedding Predictive Architecture (JEPA), bypassing keyword limitations and avoiding contrastive sample biases.

---

## 1. Architectural Philosophy
Traditional search models (like BM25 or static Bi-Encoders) map text to rigid vector spaces based on present keywords. JEPA shifts this paradigm by learning a **predictive world model** of scientific evolution.

Instead of training the network to say what a text *is*, JEPA is trained to predict the *latent representation* of a future or missing piece of research given an existing context. For a scientist graph, this means the embedding space naturally clusters researchers not just by the terminology they use, but by the **latent trajectory of their expertise**.

[Image of Joint-Embedding Predictive Architecture block diagram showing Context Encoder, Target Encoder, and Predictor]

---

## 2. Core Components of the JEPA Engine

The architecture consists of three primary neural modules operating over a shared latent space $\mathcal{Z} \in \mathbb{R}^{d}$ (where $d = 768$ or $1024$).

### A. The Context Encoder ($E_\phi$)
* **Role:** Processes the available historical/known signal of a scientist (e.g., historical titles + abstracts, or a specific query topic).
* **Backbone:** Transformer Encoder (e.g., SciBERT or RoBERTa-base, ~110M–350M parameters).
* **Output:** Context embedding $\mathbf{s}_c \in \mathbb{R}^d$.

### B. The Target Encoder ($E_	heta$)
* **Role:** Processes the target text (e.g., a subsequent publication by the same scientist, or a masked abstract paragraph).
* **Weights:** Exponential Moving Average (EMA) of the Context Encoder weights ($	heta \leftarrow 	au	heta + (1-	au)\phi$) to prevent representation collapse without needing negative pairs.
* **Output:** Target embedding $\mathbf{z}_t \in \mathbb{R}^d$.

### C. The Predictor ($P_\psi$)
* **Role:** A narrow, non-generative Transformer or Multi-Layer Perceptron (MLP) bottleneck. It takes the context embedding $\mathbf{s}_c$ and a positional/task mask vector $\mathbf{m}$ to predict the target embedding.
* **Output:** Predicted target representation $\hat{\mathbf{z}}_t \in \mathbb{R}^d$.

---

## 3. Data Engineering & Masking Strategy
With a dataset comprised strictly of **titles and abstracts** across 150,000 scientists, the model relies on intra-document and cross-document masking to build its predictive world model.

### Strategy 1: Intra-Document Prediction (Document Level)
To teach the model scientific terminology and conceptual links:
* **Context:** Paper Title + First Sentence of Abstract.
* **Target:** The remainder of the Abstract.
* **Objective:** Predict the latent essence of the technical implementation (Target) purely from the high-level conceptual framing (Context).

### Strategy 2: Cross-Document Trajectory Prediction (Scientist Level)
To capture how expertise shifts over time:
* **Context:** Abstracts from Scientist $X$ published in years $T_{-2}$ and $T_{-1}$.
* **Target:** Abstracts from Scientist $X$ published in year $T_0$.
* **Objective:** Force the latent space to arrange itself such that moving along a vector direction corresponds to logical scientific progression.

---

## 4. Mathematical Formulation & Loss Function

To prevent representation collapse (where all encoders output a constant vector), the architecture implements an **L2 Hinge Loss** combined with variance/covariance regularization (inspired by VICReg) on the latent representations.

### 1. Mean Squared Error (Prediction Loss)
The primary objective is for the predictor to accurately match the target embedding:
$$\mathcal{L}_{	ext{pred}} = rac{1}{B} \sum_{i=1}^B \|\hat{\mathbf{z}}_{t,i} - \mathbf{z}_{t,i}\|_2^2$$

### 2. Variance Regularization
Forces the embeddings within a batch $B$ to maintain distinct values, preventing collapse to a single point:
$$\mathcal{L}_{	ext{var}} = rac{1}{d} \sum_{j=1}^d \max\left(0, 1 - \sqrt{	ext{Var}(\mathbf{Z}_{:,j}) + \epsilon}
ight)$$

### 3. Total Criterion
$$\mathcal{L}_{	ext{total}} =  lpha \mathcal{L}_{	ext{pred}} +  eta \mathcal{L}_{	ext{var}}$$

---

## 5. Storage, Indexing, and Search Topology

Once trained, the Predictor module is decoupled. Only the **Context Encoder ($E_\phi$)** is deployed for indexing and production search queries.

```
+------------------------------------------------------------------------+
|                          INFERENCE PIPELINE                            |
+------------------------------------------------------------------------+

 [User Query: "Room-temp superconductivity"]
                     │
                     ▼
           ┌───────────────────┐
           │  Context Encoder  │
           └───────────────────┘
                     │
                     ▼
         Query Vector (z_query)
                     │
                     ▼
         ┌───────────────────────┐
         │ Vector DB (150k Nodes)│ ──> Dense Similarity Match
         └───────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Top K Scientist IDs   │
         └───────────────────────┘
                     │
                     ▼
       ┌───────────────────────────┐
       │ Graph Re-Ranking Module   │ <── Co-authorship & Citation Matrix
       └───────────────────────────┘
                     │
                     ▼
       Final Recommendation Scores (W_ij)
```

### Vector Database Specifications
* **Hardware footprint:** 150,000 entries $	imes$ 1024 dimensions (Float32) $ pprox$ **614 MB**. This fits entirely within a low-cost RAM instance or basic cloud container.
* **Engine Recommendation:** Use **FAISS** (for bare-metal speed) or **Qdrant / Milvus** (if metadata filtering like *H-Index, Institution, or Publication Year* needs to happen alongside vector search).
* **Index Type:** HNSW (Hierarchical Navigable Small World) for sub-millisecond retrieval.

---

## 6. Cold Start Mitigation Protocols

| Scenario | Data Available | JEPA Mitigation Strategy |
| :--- | :--- | :--- |
| **The New PhD** | 1 Solo Abstract, No Citations | **Hierarchical Split:** Run the title through $E_\phi$. Match against the database to find the 5 nearest neighboring *papers*. Initialize the scientist vector at the spatial centroid of those paper coordinates. |
| **The Veteran External** | List of Citations / Bibliography only | **Proxy Synthesis:** Extract the titles/abstracts of the papers in their bibliography. Pass them through $E_\phi$, average the vectors, and use the JEPA **Predictor ($P_\psi$)** to project where a scientist consuming that data would write their next paper. |
| **The Industry Expert** | Text-based Bio or Industry Keywords | **Cross-Modal Mapping:** Treat the raw text description as a partial context mask. The encoder maps this unstructured description directly into the scientific latent space. |

---

## 7. Concrete Step-by-Step Implementation Roadmap

### Phase 1: Data Preparation (Days 1–3)
1. Aggregate your dataset into an explicit schema: `[Scientist_ID, Paper_ID, Year, Title, Abstract]`.
2. Clean text fields (strip markdown, normalize unicode expressions).
3. Sort each scientist's papers chronologically.

### Phase 2: Model Configuration & Training (Days 4–7)
1. Initialize a `HuggingFace` model checkpoint (e.g., `allenai/scibert_scivocab_uncased`) to serve as the structural framework for $E_\phi$ and $E_	heta$.
2. Implement the EMA update hook inside your PyTorch Lightning optimization loop.
3. Train for 10–15 epochs on a single GPU (RTX 4090 or A100). Monitor variance loss to ensure the space isn't collapsing.

### Phase 3: Indexing and Production Run (Days 8–10)
1. Pass all historical abstracts through the frozen $E_\phi$.
2. Compute the composite embedding for each scientist:
   $$\mathbf{z}_{	ext{scientist}} = \sum_{k} w_k \cdot E_\phi(	ext{paper}_k)$$
   *(Where $w_k$ is a time-decay weight giving more importance to recent publications).*
3. Upsert the 150k vectors into your chosen Vector DB.
4. Expose an API endpoint: `POST /search` accepting a semantic topic string, returning the top $K$ scientists instantly.