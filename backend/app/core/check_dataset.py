from datasets import load_dataset

dataset = load_dataset("lang-uk/recruitment-dataset-job-descriptions-english")
# print(dataset)
# print("---")
# print(dataset["train"][0])


python_jobs = dataset["train"].filter(lambda x: x["Primary Keyword"] == "Python")
one_job = python_jobs[0]
for key, value in one_job.items():
    print(f"{key}: {value}\n")
