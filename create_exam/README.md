# Create SEI Exam Example

An example script that creates an SEI exam, gets the integration credentials for that exam, and then uses those credentials edit the exam.

Make sure your app requests edit_exam_settings permissions.

The script deletes the exam when it is done.

To run, clone the repo, install the requirements, and run "python create_exam.py"

Or, if you have docker, just type "docker run -it caveon/create_exam_example"
