from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

def calculate_match_score(job_desc, required_skills,
                          resume_text, resume_skills):

    documents = [job_desc, resume_text]

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(documents)

    similarity = cosine_similarity(
        tfidf_matrix[0:1],
        tfidf_matrix[1:2]
    )[0][0]

    required_skills = [s.strip().lower() for s in required_skills]
    resume_skills = [s.lower() for s in resume_skills]

    print("Required skills:", required_skills)
    print("Extracted skills:", resume_skills)

    matched = []

    for req_skill in required_skills:
        for res_skill in resume_skills:
            if req_skill in res_skill or res_skill in req_skill:
                matched.append(req_skill)
                break

    skill_score = len(matched) / len(required_skills) if required_skills else 0

    final_score = (similarity * 0.4 + skill_score * 0.6) * 100
    final_score = np.clip(final_score, 0, 100)

    return final_score, matched
