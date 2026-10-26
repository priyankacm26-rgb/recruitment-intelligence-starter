USE recruitment_intelligence_dev;
INSERT INTO candidates(first_name,last_name,email,city,current_title,years_experience,skills,source) VALUES
('Asha','Rao','asha.demo@example.com','Bengaluru','Data Analyst',3.5,JSON_ARRAY('SQL','Python','Power BI'),'sample'),
('Ravi','Kumar','ravi.demo@example.com','Mysuru','Python Developer',4,JSON_ARRAY('Python','FastAPI','MySQL'),'sample'),
('Neha','Shah','neha.demo@example.com','Bengaluru','BI Analyst',2,JSON_ARRAY('SQL','Power BI','Excel'),'sample')
ON DUPLICATE KEY UPDATE first_name=VALUES(first_name);
INSERT INTO jobs(title,description,source) VALUES ('Data Analyst','SQL, Power BI, dashboards','sample'),('Python Developer','Python APIs and MySQL','sample');
