from sentence_transformers import SentenceTransformer, util

class SimpleGeneratorEvaluator:
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        self.embedder = SentenceTransformer(model_name)

    def faithfulness(self, generated, truth):
        truth_words = truth.split()
        hits = sum(1 for w in truth_words if w in generated)
        return hits / len(truth_words)

    def evaluate(self, query, generated, truth):
        q_emb = self.embedder.encode(query, convert_to_tensor=True)
        a_emb = self.embedder.encode(generated, convert_to_tensor=True)
        t_emb = self.embedder.encode(truth, convert_to_tensor=True)

        relevance = float(util.cos_sim(a_emb, q_emb))
        correctness = float(util.cos_sim(a_emb, t_emb))
        faithful = self.faithfulness(generated, truth)

        return {
            "answer_relevance": relevance,
            "answer_correctness": correctness,
            "faithfulness": faithful,
            "final_score": (relevance + correctness + faithful) / 3
        }
