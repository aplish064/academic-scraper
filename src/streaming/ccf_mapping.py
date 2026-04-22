"""
CCF Venue Mapping - 完整版 (2026年更新)
中国计算机学会推荐国际学术会议和期刊目录（第七版）完整映射表
包含295个期刊和386个会议（A/B/C类）
从官方网站https://ccf.atom.im/提取
总计681个venue
更新时间: 2026-04-22
"""

import re
from typing import Dict, Optional, Union

# 所有CCF venue的统一映射表
CCF_VENUES = {
    "TOCS": {"ccf_class": "A", "full_name": "ACM Transactions on Computer Systems", "type": "journal"},
    "TOS": {"ccf_class": "A", "full_name": "ACM Transactions on Storage", "type": "journal"},
    "TCAD": {"ccf_class": "A", "full_name": "IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems", "type": "journal"},
    "TC": {"ccf_class": "A", "full_name": "IEEE Transactions on Computers", "type": "journal"},
    "TPDS": {"ccf_class": "A", "full_name": "IEEE Transactions on Parallel and Distributed Systems", "type": "journal"},
    "TACO": {"ccf_class": "A", "full_name": "ACM Transactions on Architecture and Code Optimization", "type": "journal"},
    "TAAS": {"ccf_class": "B", "full_name": "ACM Transactions on Autonomous and Adaptive Systems", "type": "journal"},
    "TODAES": {"ccf_class": "B", "full_name": "ACM Transactions on Design Automation of Electronic Systems", "type": "journal"},
    "TECS": {"ccf_class": "B", "full_name": "ACM Transactions on Embedded Computing Systems", "type": "journal"},
    "TRETS": {"ccf_class": "B", "full_name": "ACM Transactions on Reconfigurable Technology and Systems", "type": "journal"},
    "TVLSI": {"ccf_class": "B", "full_name": "IEEE Transactions on Very Large Scale Integration (VLSI) Systems", "type": "journal"},
    "JPDC": {"ccf_class": "B", "full_name": "Journal of Parallel and Distributed Computing", "type": "journal"},
    "JSA": {"ccf_class": "B", "full_name": "Journal of Systems Architecture: Embedded Software Design", "type": "journal"},
    "TCC": {"ccf_class": "B", "full_name": "IEEE Transactions on Cloud Computing", "type": "journal"},
    "JETC": {"ccf_class": "C", "full_name": "ACM Journal on Emerging Technologies in Computing Systems", "type": "journal"},
    "DC": {"ccf_class": "C", "full_name": "Distributed Computing", "type": "journal"},
    "FGCS": {"ccf_class": "C", "full_name": "Future Generation Computer Systems", "type": "journal"},
    "Integration": {"ccf_class": "C", "full_name": "Integration, the VLSI Journal", "type": "journal"},
    "JETTA": {"ccf_class": "C", "full_name": "Journal of Electronic Testing-Theory and Applications", "type": "journal"},
    "JGC": {"ccf_class": "C", "full_name": "The Journal of Grid computing", "type": "journal"},
    "RTS": {"ccf_class": "C", "full_name": "Real-Time Systems", "type": "journal"},
    "TJSC": {"ccf_class": "C", "full_name": "The Journal of Supercomputing", "type": "journal"},
    "TCASI": {"ccf_class": "C", "full_name": "IEEE Transactions on Circuits and Systems I: Regular Papers", "type": "journal"},
    "CCF-THPC": {"ccf_class": "C", "full_name": "CCF Transactions on High Performance Computing", "type": "journal"},
    "TSUSC": {"ccf_class": "C", "full_name": "IEEE Transactions on Sustainable Computing", "type": "journal"},
    "JSAC": {"ccf_class": "A", "full_name": "IEEE Journal on Selected Areas in Communications", "type": "journal"},
    "TMC": {"ccf_class": "A", "full_name": "IEEE Transactions on Mobile Computing", "type": "journal"},
    "TON": {"ccf_class": "A", "full_name": "IEEE Transactions on Networking", "type": "journal"},
    "TOIT": {"ccf_class": "B", "full_name": "ACM Transactions on Internet Technology", "type": "journal"},
    "TOMM": {"ccf_class": "B", "full_name": "ACM Transactions on Multimedia Computing, Communications and Applications", "type": "journal"},
    "TOSN": {"ccf_class": "B", "full_name": "ACM Transactions on Sensor Networks", "type": "journal"},
    "CN": {"ccf_class": "B", "full_name": "Computer Networks", "type": "journal"},
    "TCOM": {"ccf_class": "B", "full_name": "IEEE Transactions on Communications", "type": "journal"},
    "TWC": {"ccf_class": "B", "full_name": "IEEE Transactions on Wireless Communications", "type": "journal"},
    "CC": {"ccf_class": "C", "full_name": "Computer Communications", "type": "journal"},
    "TNSM": {"ccf_class": "C", "full_name": "IEEE Transactions on Network and Service Management", "type": "journal"},
    "JNCA": {"ccf_class": "C", "full_name": "Journal of Network and Computer Applications", "type": "journal"},
    "MONET": {"ccf_class": "C", "full_name": "Mobile Networks and Applications", "type": "journal"},
    "PPNA": {"ccf_class": "C", "full_name": "Peer-to-Peer Networking and Applications", "type": "journal"},
    "WCMC": {"ccf_class": "C", "full_name": "Wireless Communications and Mobile Computing", "type": "journal"},
    "IOT": {"ccf_class": "C", "full_name": "IEEE Internet of Things Journal", "type": "journal"},
    "TIOT": {"ccf_class": "C", "full_name": "ACM Transactions on Internet of Things", "type": "journal"},
    "TDSC": {"ccf_class": "A", "full_name": "IEEE Transactions on Dependable and Secure Computing", "type": "journal"},
    "TIFS": {"ccf_class": "A", "full_name": "IEEE Transactions on Information Forensics and Security", "type": "journal"},
    "TOPS": {"ccf_class": "B", "full_name": "ACM Transactions on Privacy and Security", "type": "journal"},
    "JCS": {"ccf_class": "B", "full_name": "Journal of Computer Security", "type": "journal"},
    "Cybersecurity": {"ccf_class": "B", "full_name": "Cybersecurity", "type": "journal"},
    "CLSR": {"ccf_class": "C", "full_name": "Computer Law & Security Review", "type": "journal"},
    "IMCS": {"ccf_class": "C", "full_name": "Information and Computer Security", "type": "journal"},
    "IJICS": {"ccf_class": "C", "full_name": "International Journal of Information and Computer Security", "type": "journal"},
    "IJISP": {"ccf_class": "C", "full_name": "International Journal of Information Security and Privacy", "type": "journal"},
    "JISA": {"ccf_class": "C", "full_name": "Journal of Information Security and Applications", "type": "journal"},
    "SCN": {"ccf_class": "C", "full_name": "Security and Communication Networks", "type": "journal"},
    "HCC": {"ccf_class": "C", "full_name": "High-Confidence Computing", "type": "journal"},
    "TOPLAS": {"ccf_class": "A", "full_name": "ACM Transactions on Programming Languages and Systems", "type": "journal"},
    "TOSEM": {"ccf_class": "A", "full_name": "ACM Transactions on Software Engineering and Methodology", "type": "journal"},
    "TSE": {"ccf_class": "A", "full_name": "IEEE Transactions on Software Engineering", "type": "journal"},
    "TSC": {"ccf_class": "A", "full_name": "IEEE Transactions on Services Computing", "type": "journal"},
    "ASE": {"ccf_class": "B", "full_name": "Automated Software Engineering", "type": "journal"},
    "ESE": {"ccf_class": "B", "full_name": "Empirical Software Engineering", "type": "journal"},
    "IETS": {"ccf_class": "B", "full_name": "IET Software", "type": "journal"},
    "IST": {"ccf_class": "B", "full_name": "Information and Software Technology", "type": "journal"},
    "JFP": {"ccf_class": "B", "full_name": "Journal of Functional Programming", "type": "journal"},
    "JSS": {"ccf_class": "B", "full_name": "Journal of Systems and Software", "type": "journal"},
    "RE": {"ccf_class": "B", "full_name": "Requirements Engineering", "type": "journal"},
    "SCP": {"ccf_class": "B", "full_name": "Science of Computer Programming", "type": "journal"},
    "SoSyM": {"ccf_class": "B", "full_name": "Software and Systems Modeling", "type": "journal"},
    "STVR": {"ccf_class": "B", "full_name": "Software Testing, Verification and Reliability", "type": "journal"},
    "SPE": {"ccf_class": "B", "full_name": "Software: Practice and Experience", "type": "journal"},
    "CL": {"ccf_class": "C", "full_name": "Computer Languages, Systems and Structures", "type": "journal"},
    "IJSEKE": {"ccf_class": "C", "full_name": "International Journal of Software Engineering and Knowledge Engineering", "type": "journal"},
    "STTT": {"ccf_class": "C", "full_name": "International Journal of Software Tools for Technology Transfer", "type": "journal"},
    "JLAMP": {"ccf_class": "C", "full_name": "Journal of Logical and Algebraic Methods in Programming", "type": "journal"},
    "JWE": {"ccf_class": "C", "full_name": "Journal of Web Engineering", "type": "journal"},
    "SOCA": {"ccf_class": "C", "full_name": "Service Oriented Computing and Applications", "type": "journal"},
    "SQJ": {"ccf_class": "C", "full_name": "Software Quality Journal", "type": "journal"},
    "TPLP": {"ccf_class": "C", "full_name": "Theory and Practice of Logic Programming", "type": "journal"},
    "PACM PL": {"ccf_class": "C", "full_name": "Proceedings of the ACM on Programming Languages", "type": "journal"},
    "TODS": {"ccf_class": "A", "full_name": "ACM Transactions on Database Systems", "type": "journal"},
    "TOIS": {"ccf_class": "A", "full_name": "ACM Transactions on Information Systems", "type": "journal"},
    "TKDE": {"ccf_class": "A", "full_name": "IEEE Transactions on Knowledge and Data Engineering", "type": "journal"},
    "VLDBJ": {"ccf_class": "A", "full_name": "The VLDB Journal", "type": "journal"},
    "TKDD": {"ccf_class": "B", "full_name": "ACM Transactions on Knowledge Discovery from Data", "type": "journal"},
    "TWEB": {"ccf_class": "B", "full_name": "ACM Transactions on the Web", "type": "journal"},
    "AEI": {"ccf_class": "B", "full_name": "Advanced Engineering Informatics", "type": "journal"},
    "DKE": {"ccf_class": "B", "full_name": "Data & Knowledge Engineering", "type": "journal"},
    "DMKD": {"ccf_class": "B", "full_name": "Data Mining and Knowledge Discovery", "type": "journal"},
    "EJIS": {"ccf_class": "B", "full_name": "European Journal of Information Systems", "type": "journal"},
    "IPM": {"ccf_class": "B", "full_name": "Information Processing and Management", "type": "journal"},
    "IS": {"ccf_class": "B", "full_name": "Information Systems", "type": "journal"},
    "JASIST": {"ccf_class": "B", "full_name": "Journal of the Association for Information Science and Technology", "type": "journal"},
    "JWS": {"ccf_class": "B", "full_name": "Journal of Web Semantics", "type": "journal"},
    "KAIS": {"ccf_class": "B", "full_name": "Knowledge and Information Systems", "type": "journal"},
    "DSE": {"ccf_class": "B", "full_name": "Data Science and Engineering", "type": "journal"},
    "DPD": {"ccf_class": "C", "full_name": "Distributed and Parallel Databases", "type": "journal"},
    "I&M": {"ccf_class": "C", "full_name": "Information & Management", "type": "journal"},
    "IPL": {"ccf_class": "C", "full_name": "Information Processing Letters", "type": "journal"},
    "IJCIS": {"ccf_class": "C", "full_name": "International Journal of Cooperative Information Systems", "type": "journal"},
    "IJGIS": {"ccf_class": "C", "full_name": "International Journal of Geographical Information Science", "type": "journal"},
    "IJIS": {"ccf_class": "C", "full_name": "International Journal of Intelligent Systems", "type": "journal"},
    "IJKM": {"ccf_class": "C", "full_name": "International Journal of Knowledge Management", "type": "journal"},
    "IJSWIS": {"ccf_class": "C", "full_name": "International Journal on Semantic Web and Information Systems", "type": "journal"},
    "JCIS": {"ccf_class": "C", "full_name": "Journal of Computer Information Systems", "type": "journal"},
    "JDM": {"ccf_class": "C", "full_name": "Journal of Database Management", "type": "journal"},
    "JGITM": {"ccf_class": "C", "full_name": "Journal of Global Information Technology Management", "type": "journal"},
    "JIIS": {"ccf_class": "C", "full_name": "Journal of Intelligent Information Systems", "type": "journal"},
    "JSIS": {"ccf_class": "C", "full_name": "The Journal of Strategic Information Systems", "type": "journal"},
    "TIST": {"ccf_class": "C", "full_name": "ACM Transactions on Intelligent Systems and Technology", "type": "journal"},
    "TORS": {"ccf_class": "C", "full_name": "ACM Transactions on Recommender Systems", "type": "journal"},
    "TIT": {"ccf_class": "A", "full_name": "IEEE Transactions on Information Theory", "type": "journal"},
    "IANDC": {"ccf_class": "A", "full_name": "Information and Computation", "type": "journal"},
    "SICOMP": {"ccf_class": "A", "full_name": "SIAM Journal on Computing", "type": "journal"},
    "TALG": {"ccf_class": "B", "full_name": "ACM Transactions on Algorithms", "type": "journal"},
    "TOCL": {"ccf_class": "B", "full_name": "ACM Transactions on Computational Logic", "type": "journal"},
    "TOMS": {"ccf_class": "B", "full_name": "ACM Transactions on Mathematical Software", "type": "journal"},
    "Algorithmica": {"ccf_class": "B", "full_name": "Algorithmica", "type": "journal"},
    "CC": {"ccf_class": "B", "full_name": "Computational complexity", "type": "journal"},
    "FAC": {"ccf_class": "B", "full_name": "Formal Aspects of Computing", "type": "journal"},
    "FMSD": {"ccf_class": "B", "full_name": "Formal Methods in System Design", "type": "journal"},
    "INFORMS": {"ccf_class": "B", "full_name": "INFORMS Journal on Computing", "type": "journal"},
    "JCSS": {"ccf_class": "B", "full_name": "Journal of Computer and System Sciences", "type": "journal"},
    "JGO": {"ccf_class": "B", "full_name": "Journal of Global Optimization", "type": "journal"},
    "JSC": {"ccf_class": "B", "full_name": "Journal of Symbolic Computation", "type": "journal"},
    "MSCS": {"ccf_class": "B", "full_name": "Mathematical Structures in Computer Science", "type": "journal"},
    "TCS": {"ccf_class": "B", "full_name": "Theoretical Computer Science", "type": "journal"},
    "ACTA": {"ccf_class": "C", "full_name": "Acta Informatica", "type": "journal"},
    "APAL": {"ccf_class": "C", "full_name": "Annals of Pure and Applied Logic", "type": "journal"},
    "DAM": {"ccf_class": "C", "full_name": "Discrete Applied Mathematics", "type": "journal"},
    "FUIN": {"ccf_class": "C", "full_name": "Fundamenta Informaticae", "type": "journal"},
    "IPL": {"ccf_class": "C", "full_name": "Information Processing Letters", "type": "journal"},
    "JCOMPLEXITY": {"ccf_class": "C", "full_name": "Journal of Complexity", "type": "journal"},
    "LOGCOM": {"ccf_class": "C", "full_name": "Journal of Logic and Computation", "type": "journal"},
    "JSL": {"ccf_class": "C", "full_name": "The Journal of Symbolic Logic", "type": "journal"},
    "LMCS": {"ccf_class": "C", "full_name": "Logical Methods in Computer Science", "type": "journal"},
    "SIDMA": {"ccf_class": "C", "full_name": "SIAM Journal on Discrete Mathematics", "type": "journal"},
    "TQC": {"ccf_class": "C", "full_name": "ACM Transactions in Quantum Computing", "type": "journal"},
    "TOG": {"ccf_class": "A", "full_name": "ACM Transactions on Graphics", "type": "journal"},
    "TIP": {"ccf_class": "A", "full_name": "IEEE Transactions on Image Processing", "type": "journal"},
    "TVCG": {"ccf_class": "A", "full_name": "IEEE Transactions on Visualization and Computer Graphics", "type": "journal"},
    "TMM": {"ccf_class": "A", "full_name": "IEEE Transactions on Multimedia", "type": "journal"},
    "TOMM": {"ccf_class": "B", "full_name": "ACM Transactions on Multimedia Computing,Communications and Applications", "type": "journal"},
    "CAGD": {"ccf_class": "B", "full_name": "Computer Aided Geometric Design", "type": "journal"},
    "CGF": {"ccf_class": "B", "full_name": "Computer Graphics Forum", "type": "journal"},
    "CAD": {"ccf_class": "B", "full_name": "Computer-Aided Design", "type": "journal"},
    "TCSVT": {"ccf_class": "B", "full_name": "IEEE Transactions on Circuits and Systems for Video Technology", "type": "journal"},
    "JASA": {"ccf_class": "B", "full_name": "The Journal of the Acoustical Society of America", "type": "journal"},
    "SIIMS": {"ccf_class": "B", "full_name": "SIAM Journal on Imaging Sciences", "type": "journal"},
    "SPECOM": {"ccf_class": "B", "full_name": "Speech Communication", "type": "journal"},
    "CVMJ": {"ccf_class": "B", "full_name": "Computational Visual Media", "type": "journal"},
    "CGTA": {"ccf_class": "C", "full_name": "Computational Geometry: Theory and Applications", "type": "journal"},
    "CAVW": {"ccf_class": "C", "full_name": "computer animation & virtual worlds", "type": "journal"},
    "C&G": {"ccf_class": "C", "full_name": "Computers & Graphics", "type": "journal"},
    "DCG": {"ccf_class": "C", "full_name": "Discrete & Computational Geometry", "type": "journal"},
    "SPL": {"ccf_class": "C", "full_name": "IEEE Signal Processing Letters", "type": "journal"},
    "IET-IPR": {"ccf_class": "C", "full_name": "IET Image Processing", "type": "journal"},
    "JVCIR": {"ccf_class": "C", "full_name": "Journal of Visual Communication and Image Representation", "type": "journal"},
    "MS": {"ccf_class": "C", "full_name": "Multimedia Systems", "type": "journal"},
    "MTA": {"ccf_class": "C", "full_name": "Multimedia Tools and Applications", "type": "journal"},
    "SIGPRO": {"ccf_class": "C", "full_name": "Signal Processing", "type": "journal"},
    "IMAGE": {"ccf_class": "C", "full_name": "Signal Processing: Image Communication", "type": "journal"},
    "TVC": {"ccf_class": "C", "full_name": "The Visual Computer", "type": "journal"},
    "VI": {"ccf_class": "C", "full_name": "Visual Informatics", "type": "journal"},
    "VRIH": {"ccf_class": "C", "full_name": "Virtual Reality & Intelligent Hardware", "type": "journal"},
    "GMOD": {"ccf_class": "C", "full_name": "Graphical Models", "type": "journal"},
    "AI": {"ccf_class": "A", "full_name": "Artificial Intelligence", "type": "journal"},
    "TPAMI": {"ccf_class": "A", "full_name": "IEEE Transactions on Pattern Analysis and Machine Intelligence", "type": "journal"},
    "IJCV": {"ccf_class": "A", "full_name": "International Journal of Computer Vision", "type": "journal"},
    "JMLR": {"ccf_class": "A", "full_name": "Journal of Machine Learning Research", "type": "journal"},
    "TAP": {"ccf_class": "B", "full_name": "ACM Transactions on Applied Perception", "type": "journal"},
    "AAMAS": {"ccf_class": "B", "full_name": "Autonomous Agents and Multi-Agent Systems", "type": "journal"},
    "CVIU": {"ccf_class": "B", "full_name": "Computer Vision and Image Understanding", "type": "journal"},
    "DKE": {"ccf_class": "B", "full_name": "Data & Knowledge Engineering", "type": "journal"},
    "TAC": {"ccf_class": "B", "full_name": "IEEE Transactions on Affective Computing", "type": "journal"},
    "TASLP": {"ccf_class": "B", "full_name": "IEEE Transactions on Audio, Speech and Language Processing", "type": "journal"},
    "TEC": {"ccf_class": "B", "full_name": "IEEE Transactions on Evolutionary Computation", "type": "journal"},
    "TFS": {"ccf_class": "B", "full_name": "IEEE Transactions on Fuzzy Systems", "type": "journal"},
    "TNNLS": {"ccf_class": "B", "full_name": "IEEE Transactions on Neural Networks and learning systems", "type": "journal"},
    "IJAR": {"ccf_class": "B", "full_name": "International Journal of Approximate Reasoning", "type": "journal"},
    "JAIR": {"ccf_class": "B", "full_name": "Journal of Artificial Intelligence Research", "type": "journal"},
    "JSLHR": {"ccf_class": "B", "full_name": "Journal of Speech, Language, and Hearing Research", "type": "journal"},
    "PR": {"ccf_class": "B", "full_name": "Pattern Recognition", "type": "journal"},
    "TACL": {"ccf_class": "B", "full_name": "Transactions of the Association for Computational Linguistics", "type": "journal"},
    "TALLIP": {"ccf_class": "C", "full_name": "ACM Transactions on Asian and Low-Resource Language Information Processing", "type": "journal"},
    "AIM": {"ccf_class": "C", "full_name": "Artificial Intelligence in Medicine", "type": "journal"},
    "DSS": {"ccf_class": "C", "full_name": "Decision Support Systems", "type": "journal"},
    "EAAI": {"ccf_class": "C", "full_name": "Engineering Applications of Artificial Intelligence", "type": "journal"},
    "ESWA": {"ccf_class": "C", "full_name": "Expert Systems with Applications", "type": "journal"},
    "TG": {"ccf_class": "C", "full_name": "IEEE Transactions on Games", "type": "journal"},
    "IET-CVI": {"ccf_class": "C", "full_name": "IET Computer Vision", "type": "journal"},
    "IVC": {"ccf_class": "C", "full_name": "Image and Vision Computing", "type": "journal"},
    "IDA": {"ccf_class": "C", "full_name": "Intelligent Data Analysis", "type": "journal"},
    "IJCIA": {"ccf_class": "C", "full_name": "International Journal of Computational Intelligence and Applications", "type": "journal"},
    "IJIS": {"ccf_class": "C", "full_name": "International Journal of Intelligent Systems", "type": "journal"},
    "IJNS": {"ccf_class": "C", "full_name": "International Journal of Neural Systems", "type": "journal"},
    "IJPRAI": {"ccf_class": "C", "full_name": "International Journal of Pattern Recognition and Artificial Intelligence", "type": "journal"},
    "IJUFKS": {"ccf_class": "C", "full_name": "International Journal of Uncertainty,Fuzziness and Knowledge-Based Systems", "type": "journal"},
    "IJDAR": {"ccf_class": "C", "full_name": "International Journal on Document Analysis and Recognition", "type": "journal"},
    "JETAI": {"ccf_class": "C", "full_name": "Journal of Experimental and Theoretical Artificial Intelligence", "type": "journal"},
    "KBS": {"ccf_class": "C", "full_name": "Knowledge-Based Systems", "type": "journal"},
    "NLE": {"ccf_class": "C", "full_name": "Natural Language Engineering", "type": "journal"},
    "NCA": {"ccf_class": "C", "full_name": "Neural Computing and Applications", "type": "journal"},
    "NPL": {"ccf_class": "C", "full_name": "Neural Processing Letters", "type": "journal"},
    "PAA": {"ccf_class": "C", "full_name": "Pattern Analysis and Applications", "type": "journal"},
    "PRL": {"ccf_class": "C", "full_name": "Pattern Recognition Letters", "type": "journal"},
    "WI": {"ccf_class": "C", "full_name": "Web Intelligence", "type": "journal"},
    "TIIS": {"ccf_class": "C", "full_name": "ACM Transactions on Interactive Intelligent Systems", "type": "journal"},
    "TELO": {"ccf_class": "C", "full_name": "ACM Transactions on Evolutionary Learning and Optimization", "type": "journal"},
    "JATS": {"ccf_class": "C", "full_name": "ACM Journal on Autonomous Transportation Systems", "type": "journal"},
    "TOCHI": {"ccf_class": "A", "full_name": "ACM Transactions on Computer-Human Interaction", "type": "journal"},
    "IJHCS": {"ccf_class": "A", "full_name": "International Journal of Human-Computer Studies", "type": "journal"},
    "CSCW": {"ccf_class": "B", "full_name": "Computer Supported Cooperative Work", "type": "journal"},
    "HCI": {"ccf_class": "B", "full_name": "Human-Computer Interaction", "type": "journal"},
    "IWC": {"ccf_class": "B", "full_name": "Interacting with Computers", "type": "journal"},
    "IJHCI": {"ccf_class": "B", "full_name": "International Journal of Human-Computer Interaction", "type": "journal"},
    "UMUAI": {"ccf_class": "B", "full_name": "User Modeling and User-Adapted Interaction", "type": "journal"},
    "TSMC": {"ccf_class": "B", "full_name": "IEEE Transactions on Systems, Man, and Cybernetics: Systems", "type": "journal"},
    "CCF TPCI": {"ccf_class": "B", "full_name": "CCF Transactions on Pervasive Computing and Interaction", "type": "journal"},
    "BIT": {"ccf_class": "C", "full_name": "Behaviour & Information Technology", "type": "journal"},
    "PUC": {"ccf_class": "C", "full_name": "Personal and Ubiquitous Computing", "type": "journal"},
    "PMC": {"ccf_class": "C", "full_name": "Pervasive and Mobile Computing", "type": "journal"},
    "PACMHCI": {"ccf_class": "C", "full_name": "Proceedings of the ACM on Human-Computer Interaction", "type": "journal"},
    "THRI": {"ccf_class": "C", "full_name": "ACM Transactions on Human-Robot Interaction", "type": "journal"},
    "JACM": {"ccf_class": "A", "full_name": "Journal of the ACM", "type": "journal"},
    "Proc. IEEE": {"ccf_class": "A", "full_name": "Proceedings of the IEEE", "type": "journal"},
    "SCIS": {"ccf_class": "A", "full_name": "Science China Information Sciences", "type": "journal"},
    "Bioinformatics": {"ccf_class": "A", "full_name": "Bioinformatics", "type": "journal"},
    "Cognition": {"ccf_class": "B", "full_name": "Cognition", "type": "journal"},
    "TASAE": {"ccf_class": "B", "full_name": "IEEE Transactions on Automation Science and Engineering", "type": "journal"},
    "TGARS": {"ccf_class": "B", "full_name": "IEEE Transactions on Geoscience and Remote Sensing", "type": "journal"},
    "TITS": {"ccf_class": "B", "full_name": "IEEE Transactions on Intelligent Transportation Systems", "type": "journal"},
    "TMI": {"ccf_class": "B", "full_name": "IEEE Transactions on Medical Imaging", "type": "journal"},
    "TR": {"ccf_class": "B", "full_name": "IEEE Transactions on Robotics", "type": "journal"},
    "TCBB": {"ccf_class": "B", "full_name": "IEEE/ACM Transactions on Computational Biology and Bioinformatics", "type": "journal"},
    "JCST": {"ccf_class": "B", "full_name": "Journal of Computer Science and Technology", "type": "journal"},
    "JAMIA": {"ccf_class": "B", "full_name": "Journal of the American Medical Informatics Association", "type": "journal"},
    "WWW": {"ccf_class": "B", "full_name": "The Web Conference", "type": "journal"},
    "FCS": {"ccf_class": "B", "full_name": "Frontiers of Computer Science", "type": "journal"},
    "BCRA": {"ccf_class": "B", "full_name": "Blockchain: Research and Applications", "type": "journal"},
    "JBHI": {"ccf_class": "C", "full_name": "IEEE Journal of Biomedical and Health Informatics", "type": "journal"},
    "TBD": {"ccf_class": "C", "full_name": "IEEE Transactions on Big Data", "type": "journal"},
    "JBI": {"ccf_class": "C", "full_name": "Journal of Biomedical Informatics", "type": "journal"},
    "TII": {"ccf_class": "C", "full_name": "IEEE Transactions on Industrial Informatics", "type": "journal"},
    "TCPS": {"ccf_class": "C", "full_name": "ACM Transactions on Cyber-Physical Systems", "type": "journal"},
    "TOCE": {"ccf_class": "C", "full_name": "ACM Transactions on Computing Education", "type": "journal"},
    "EITEE": {"ccf_class": "C", "full_name": "ENGINEERING Information Technology & Electronic Engineering", "type": "journal"},
    "TCSS": {"ccf_class": "C", "full_name": "IEEE Transactions on Computational Social Systems", "type": "journal"},
    "HEALTH": {"ccf_class": "C", "full_name": "ACM Transactions on Computing for Healthcare", "type": "journal"},
    "ACM DLT": {"ccf_class": "C", "full_name": "ACM Distributed Ledger Technologies: Research and Practice", "type": "journal"},
    "PPoPP": {"ccf_class": "A", "full_name": "ACM SIGPLAN Symposium on Principles & Practice of Parallel Programming", "type": "conference"},
    "FAST": {"ccf_class": "A", "full_name": "USENIX Conference on File and Storage Technologies", "type": "conference"},
    "DAC": {"ccf_class": "A", "full_name": "Design Automation Conference", "type": "conference"},
    "HPCA": {"ccf_class": "A", "full_name": "IEEE International Symposium on High Performance Computer Architecture", "type": "conference"},
    "MICRO": {"ccf_class": "A", "full_name": "IEEE/ACM International Symposium on Microarchitecture", "type": "conference"},
    "SC": {"ccf_class": "A", "full_name": "International Conference for High Performance Computing, Networking, Storage, and Analysis", "type": "conference"},
    "ASPLOS": {"ccf_class": "A", "full_name": "International Conference on Architectural Support for Programming Languages and Operating Systems", "type": "conference"},
    "ISCA": {"ccf_class": "A", "full_name": "International Symposium on Computer Architecture", "type": "conference"},
    "ACM SIGOPS ATC": {"ccf_class": "A", "full_name": "ACM SIGOPS Annual Technical Conference", "type": "conference"},
    "EuroSys": {"ccf_class": "A", "full_name": "European Conference on Computer Systems", "type": "conference"},
    "HPDC": {"ccf_class": "A", "full_name": "The International ACM Symposium on High-Performance Parallel and Distributed Computing", "type": "conference"},
    "SoCC": {"ccf_class": "B", "full_name": "ACM Symposium on Cloud Computing", "type": "conference"},
    "SPAA": {"ccf_class": "B", "full_name": "ACM Symposium on Parallelism in Algorithms and Architectures", "type": "conference"},
    "PODC": {"ccf_class": "B", "full_name": "ACM Symposium on Principles of Distributed Computing", "type": "conference"},
    "FPGA": {"ccf_class": "B", "full_name": "ACM/SIGDA International Symposium on Field-Programmable Gate Arrays", "type": "conference"},
    "CGO": {"ccf_class": "B", "full_name": "The International Symposium on Code Generation and Optimization", "type": "conference"},
    "DATE": {"ccf_class": "B", "full_name": "Design, Automation & Test in Europe", "type": "conference"},
    "HOT CHIPS": {"ccf_class": "B", "full_name": "Hot Chips: A Symposium on High Performance Chips", "type": "conference"},
    "CLUSTER": {"ccf_class": "B", "full_name": "IEEE International Conference on Cluster Computing", "type": "conference"},
    "ICCD": {"ccf_class": "B", "full_name": "International Conference on Computer Design", "type": "conference"},
    "ICCAD": {"ccf_class": "B", "full_name": "International Conference on Computer-Aided Design", "type": "conference"},
    "ICDCS": {"ccf_class": "B", "full_name": "IEEE International Conference on Distributed Computing Systems", "type": "conference"},
    "CODES+ISSS": {"ccf_class": "B", "full_name": "International Conference on Hardware/Software Co-design and System Synthesis", "type": "conference"},
    "HiPEAC": {"ccf_class": "B", "full_name": "International Conference on High Performance and Embedded Architectures and Compilers", "type": "conference"},
    "SIGMETRICS": {"ccf_class": "B", "full_name": "International Conference on Measurement and Modeling of Computer Systems", "type": "conference"},
    "PACT": {"ccf_class": "B", "full_name": "International Conference on Parallel Architectures and Compilation Techniques", "type": "conference"},
    "ICPP": {"ccf_class": "B", "full_name": "International Conference on Parallel Processing", "type": "conference"},
    "ICS": {"ccf_class": "B", "full_name": "International Conference on Supercomputing", "type": "conference"},
    "VEE": {"ccf_class": "B", "full_name": "International Conference on Virtual Execution Environments", "type": "conference"},
    "IPDPS": {"ccf_class": "B", "full_name": "IEEE International Parallel & Distributed Processing Symposium", "type": "conference"},
    "Performance": {"ccf_class": "B", "full_name": "International Symposium on Computer Performance, Modeling, Measurements and Evaluation", "type": "conference"},
    "ITC": {"ccf_class": "B", "full_name": "International Test Conference", "type": "conference"},
    "LISA": {"ccf_class": "B", "full_name": "Large Installation System Administration Conference", "type": "conference"},
    "MSST": {"ccf_class": "B", "full_name": "Mass Storage Systems and Technologies", "type": "conference"},
    "RTAS": {"ccf_class": "B", "full_name": "IEEE Real-Time and Embedded Technology and ApplicationsSymposium", "type": "conference"},
    "Euro-Par": {"ccf_class": "B", "full_name": "European Conference on Parallel and Distributed Computing", "type": "conference"},
    "ISCAS": {"ccf_class": "B", "full_name": "IEEE International Symposium on Circuits and Systems", "type": "conference"},
    "CF": {"ccf_class": "C", "full_name": "ACM International Conference on Computing Frontiers", "type": "conference"},
    "SYSTOR": {"ccf_class": "C", "full_name": "ACM International Systems and Storage Conference", "type": "conference"},
    "NOCS": {"ccf_class": "C", "full_name": "ACM/IEEE International Symposium on Networks-on-Chip", "type": "conference"},
    "ASAP": {"ccf_class": "C", "full_name": "IEEE International Conference on Application-Specific Systems, Architectures, and Processors", "type": "conference"},
    "ASP-DAC": {"ccf_class": "C", "full_name": "Asia and South Pacific Design Automation Conference", "type": "conference"},
    "ETS": {"ccf_class": "C", "full_name": "IEEE European Test Symposium", "type": "conference"},
    "FPL": {"ccf_class": "C", "full_name": "International Conference on Field-Programmable Logic and Applications", "type": "conference"},
    "FCCM": {"ccf_class": "C", "full_name": "IEEE Symposium on Field-Programmable Custom Computing Machines", "type": "conference"},
    "GLSVLSI": {"ccf_class": "C", "full_name": "Great Lakes Symposium on VLSI", "type": "conference"},
    "ATS": {"ccf_class": "C", "full_name": "IEEE Asian Test Symposium", "type": "conference"},
    "HPCC": {"ccf_class": "C", "full_name": "IEEE International Conference on High Performance Computing and Communications", "type": "conference"},
    "HiPC": {"ccf_class": "C", "full_name": "IEEE International Conference on High Performance Computing, Data and Analytics", "type": "conference"},
    "MASCOTS": {"ccf_class": "C", "full_name": "International Symposium on Modeling, Analysis, andSimulation of Computer and Telecommunication Systems", "type": "conference"},
    "ISPA": {"ccf_class": "C", "full_name": "IEEE International Symposium on Parallel and Distributed Processing with Applications", "type": "conference"},
    "CCGRID": {"ccf_class": "C", "full_name": "IEEE/ACM International Symposium on Cluster, Cloud and Grid Computing", "type": "conference"},
    "NPC": {"ccf_class": "C", "full_name": "IFIP International Conference on Network and Parallel Computing", "type": "conference"},
    "ICA3PP": {"ccf_class": "C", "full_name": "International Conference on Algorithms and Architectures for Parallel Processing", "type": "conference"},
    "CASES": {"ccf_class": "C", "full_name": "International Conference on Compilers, Architectures, and Synthesis for Embedded Systems", "type": "conference"},
    "FPT": {"ccf_class": "C", "full_name": "International Conference on Field-Programmable Technology", "type": "conference"},
    "ICPADS": {"ccf_class": "C", "full_name": "International Conference on Parallel and Distributed Systems", "type": "conference"},
    "ISLPED": {"ccf_class": "C", "full_name": "International Symposium on Low Power Electronics and Design", "type": "conference"},
    "ISPD": {"ccf_class": "C", "full_name": "International Symposium on Physical Design", "type": "conference"},
    "HOTI": {"ccf_class": "C", "full_name": "IEEE Symposium on High-Performance Interconnects", "type": "conference"},
    "VTS": {"ccf_class": "C", "full_name": "IEEE VLSI Test Symposium", "type": "conference"},
    "ITC-Asia": {"ccf_class": "C", "full_name": "International Test Conference in Asia", "type": "conference"},
    "SEC": {"ccf_class": "C", "full_name": "ACM/IEEE Symposium on Edge Computing", "type": "conference"},
    "NAS": {"ccf_class": "C", "full_name": "International Conference on Networking, Architecture and Storages", "type": "conference"},
    "HotStorage": {"ccf_class": "C", "full_name": "Hot Topics in Storage and File Systems", "type": "conference"},
    "APPT": {"ccf_class": "C", "full_name": "International Symposium on Advanced Parallel Processing Technology", "type": "conference"},
    "JCC": {"ccf_class": "C", "full_name": "International Conference on Joint Cloud Computing", "type": "conference"},
    "SIGCOMM": {"ccf_class": "A", "full_name": "ACM International Conference on Applications, Technologies, Architectures, and Protocols for Computer Communication", "type": "conference"},
    "MobiCom": {"ccf_class": "A", "full_name": "ACM International Conference on Mobile Computing and Networking", "type": "conference"},
    "INFOCOM": {"ccf_class": "A", "full_name": "IEEE International Conference on Computer Communications", "type": "conference"},
    "NSDI": {"ccf_class": "A", "full_name": "Symposium on Network System Design and Implementation", "type": "conference"},
    "SenSys": {"ccf_class": "B", "full_name": "ACM Conference on Embedded Networked Sensor Systems", "type": "conference"},
    "CoNEXT": {"ccf_class": "B", "full_name": "ACM International Conference on emerging Networking EXperiments and Technologies", "type": "conference"},
    "SECON": {"ccf_class": "B", "full_name": "IEEE International Conference on Sensing, Communication, and Networking", "type": "conference"},
    "IPSN": {"ccf_class": "B", "full_name": "International Conference on Information Processing in Sensor Networks", "type": "conference"},
    "MobiSys": {"ccf_class": "B", "full_name": "ACM International Conference on Mobile Systems, Applications, and Services", "type": "conference"},
    "ICNP": {"ccf_class": "B", "full_name": "IEEE International Conference on Network Protocols", "type": "conference"},
    "MobiHoc": {"ccf_class": "B", "full_name": "International Symposium on Theory, Algorithmic Foundations, and Protocol Design for Mobile Networks and Mobile Computing", "type": "conference"},
    "NOSSDAV": {"ccf_class": "B", "full_name": "International Workshop on Network and Operating System Support for Digital Audio and Video", "type": "conference"},
    "IWQoS": {"ccf_class": "B", "full_name": "IEEE/ACM International Workshop on Quality of Service", "type": "conference"},
    "IMC": {"ccf_class": "B", "full_name": "ACM Internet Measurement Conference", "type": "conference"},
    "ANCS": {"ccf_class": "C", "full_name": "ACM/IEEE Symposium on Architectures for Networking and Communication Systems", "type": "conference"},
    "APNOMS": {"ccf_class": "C", "full_name": "Asia-Pacific Network Operations and Management Symposium", "type": "conference"},
    "FORTE": {"ccf_class": "C", "full_name": "International Conference on Formal Techniques for Distributed Objects, Components, and Systems", "type": "conference"},
    "LCN": {"ccf_class": "C", "full_name": "IEEE Conference on Local Computer Networks", "type": "conference"},
    "GLOBECOM": {"ccf_class": "C", "full_name": "IEEE Global Communications Conference", "type": "conference"},
    "ICC": {"ccf_class": "C", "full_name": "IEEE International Conference on Communications", "type": "conference"},
    "ICCCN": {"ccf_class": "C", "full_name": "IEEE International Conference on Computer Communications and Networks", "type": "conference"},
    "MASS": {"ccf_class": "C", "full_name": "IEEE International Conference on Mobile Ad-hoc and Sensor Systems", "type": "conference"},
    "P2P": {"ccf_class": "C", "full_name": "IEEE International Conference on P2P Computing", "type": "conference"},
    "IPCCC": {"ccf_class": "C", "full_name": "IEEE International Performance Computing and Communications Conference", "type": "conference"},
    "WoWMoM": {"ccf_class": "C", "full_name": "IEEE International Symposium on a World of Wireless Mobile and Multimedia Networks", "type": "conference"},
    "ISCC": {"ccf_class": "C", "full_name": "IEEE Symposium on Computers and Communications", "type": "conference"},
    "WCNC": {"ccf_class": "C", "full_name": "IEEE Wireless Communications and Networking Conference", "type": "conference"},
    "Networking": {"ccf_class": "C", "full_name": "IFIP International Conferences on Networking", "type": "conference"},
    "IM": {"ccf_class": "C", "full_name": "IFIP/IEEE International Symposium on Integrated NetworkManagement", "type": "conference"},
    "MSN": {"ccf_class": "C", "full_name": "International Conference on Mobility, Sensing and Networking", "type": "conference"},
    "MSWiM": {"ccf_class": "C", "full_name": "International Conference on Modeling, Analysis and Simulation of Wireless and Mobile Systems", "type": "conference"},
    "WASA": {"ccf_class": "C", "full_name": "The International Conference on Wireless Artificial Intelligent Computing Systems and Applications", "type": "conference"},
    "HotNets": {"ccf_class": "C", "full_name": "ACM The Workshop on Hot Topics in Networks", "type": "conference"},
    "APNet": {"ccf_class": "C", "full_name": "Asia-Pacific Workshop on Networking", "type": "conference"},
    "CCS": {"ccf_class": "A", "full_name": "ACM Conference on Computer and Communications Security", "type": "conference"},
    "EUROCRYPT": {"ccf_class": "A", "full_name": "International Conference on the Theory and Applications of Cryptographic Techniques", "type": "conference"},
    "S&P": {"ccf_class": "A", "full_name": "IEEE Symposium on Security and Privacy", "type": "conference"},
    "CRYPTO": {"ccf_class": "A", "full_name": "International Cryptology Conference", "type": "conference"},
    "USENIX Security": {"ccf_class": "A", "full_name": "USENIX Security Symposium", "type": "conference"},
    "NDSS": {"ccf_class": "A", "full_name": "Network and Distributed System Security Symposium", "type": "conference"},
    "ACSAC": {"ccf_class": "B", "full_name": "Annual Computer Security Applications Conference", "type": "conference"},
    "ASIACRYPT": {"ccf_class": "B", "full_name": "Annual International Conference on the Theory and Application of Cryptology and Information Security", "type": "conference"},
    "ESORICS": {"ccf_class": "B", "full_name": "European Symposium on Research in Computer Security", "type": "conference"},
    "FSE": {"ccf_class": "B", "full_name": "Fast Software Encryption", "type": "conference"},
    "CSFW": {"ccf_class": "B", "full_name": "IEEE Computer Security Foundations Workshop", "type": "conference"},
    "SRDS": {"ccf_class": "B", "full_name": "IEEE International Symposium on Reliable Distributed Systems", "type": "conference"},
    "CHES": {"ccf_class": "B", "full_name": "International Conference on Cryptographic Hardware and Embedded Systems", "type": "conference"},
    "DSN": {"ccf_class": "B", "full_name": "International Conference on Dependable Systems and Networks", "type": "conference"},
    "RAID": {"ccf_class": "B", "full_name": "International Symposium on Recent Advances in Intrusion Detection", "type": "conference"},
    "PKC": {"ccf_class": "B", "full_name": "International Workshop on Practice and Theory in Public Key Cryptography", "type": "conference"},
    "TCC": {"ccf_class": "B", "full_name": "Theory of Cryptography Conference", "type": "conference"},
    "WiSec": {"ccf_class": "C", "full_name": "ACM Conference on Security and Privacy in Wireless and Mobile Networks", "type": "conference"},
    "SACMAT": {"ccf_class": "C", "full_name": "ACM Symposium on Access Control Models and Technologies", "type": "conference"},
    "DRM": {"ccf_class": "C", "full_name": "ACM Workshop on Digital Rights Management", "type": "conference"},
    "IH&MMSec": {"ccf_class": "C", "full_name": "ACM Workshop on Information Hiding and Multimedia Security", "type": "conference"},
    "ACNS": {"ccf_class": "C", "full_name": "International Conference on Applied Cryptography and Network Security", "type": "conference"},
    "AsiaCCS": {"ccf_class": "C", "full_name": "ACM Asia Conference on Computer and Communications Security", "type": "conference"},
    "ACISP": {"ccf_class": "C", "full_name": "AustralasiaConferenceonInformation SecurityandPrivacy", "type": "conference"},
    "CT-RSA": {"ccf_class": "C", "full_name": "The Cryptographer’s Track at RSA Conference", "type": "conference"},
    "DIMVA": {"ccf_class": "C", "full_name": "Conference on Detection of Intrusions and Malware & VulnerabilityAssessment", "type": "conference"},
    "DFRWS": {"ccf_class": "C", "full_name": "Digital Forensic Research Workshop", "type": "conference"},
    "FC": {"ccf_class": "C", "full_name": "Financial Cryptography and Data Security", "type": "conference"},
    "TrustCom": {"ccf_class": "C", "full_name": "IEEE International Conference on Trust,Security and Privacy in Computing and Communications", "type": "conference"},
    "SEC": {"ccf_class": "C", "full_name": "IFIP International Information Security Conference", "type": "conference"},
    "IFIP WG 11.9": {"ccf_class": "C", "full_name": "IFIP Working Group 11.9 International Conference on Digital Forensics", "type": "conference"},
    "ISC": {"ccf_class": "C", "full_name": "Information Security Conference", "type": "conference"},
    "ICDF2C": {"ccf_class": "C", "full_name": "International Conference on Digital Forensics & Cyber Crime", "type": "conference"},
    "ICICS": {"ccf_class": "C", "full_name": "International Conference on Information and Communications Security", "type": "conference"},
    "SecureComm": {"ccf_class": "C", "full_name": "International Conference on Security and Privacy in Communication Networks", "type": "conference"},
    "NSPW": {"ccf_class": "C", "full_name": "New Security Paradigms Workshop", "type": "conference"},
    "PAM": {"ccf_class": "C", "full_name": "Passive and Active Measurement Conference", "type": "conference"},
    "PETS": {"ccf_class": "C", "full_name": "Privacy Enhancing Technologies Symposium", "type": "conference"},
    "SAC": {"ccf_class": "C", "full_name": "Selected Areas in Cryptography", "type": "conference"},
    "SOUPS": {"ccf_class": "C", "full_name": "Symposium On Usable Privacy and Security", "type": "conference"},
    "HotSec": {"ccf_class": "C", "full_name": "USENIX Workshop on Hot Topics in Security", "type": "conference"},
    "EuroS&P": {"ccf_class": "C", "full_name": "IEEE European Symposium on Security and Privacy", "type": "conference"},
    "Inscrypt": {"ccf_class": "C", "full_name": "International Conference on Information Security and Cryptology", "type": "conference"},
    "CODASPY": {"ccf_class": "C", "full_name": "Conference on Data and Application Security and Privacy", "type": "conference"},
    "BlockSys": {"ccf_class": "C", "full_name": "International Conference on Blockchain, Artificial Intelligence, and Trustworthy Systems", "type": "conference"},
    "CSCloud": {"ccf_class": "C", "full_name": "International Conference on Cyber Security and Cloud Computing", "type": "conference"},
    "PLDI": {"ccf_class": "A", "full_name": "ACM SIGPLAN Conference on Programming Language Design and Implementation", "type": "conference"},
    "POPL": {"ccf_class": "A", "full_name": "ACM SIGPLAN-SIGACT Symposium on Principles of Programming Languages", "type": "conference"},
    "FSE": {"ccf_class": "A", "full_name": "ACM International Conference on the Foundations of Software Engineering", "type": "conference"},
    "SOSP": {"ccf_class": "A", "full_name": "ACM Symposium on Operating Systems Principles", "type": "conference"},
    "OOPSLA": {"ccf_class": "A", "full_name": "Conference on Object-Oriented Programming Systems, Languages,and Applications", "type": "conference"},
    "ASE": {"ccf_class": "A", "full_name": "International Conference on Automated Software Engineering", "type": "conference"},
    "ICSE": {"ccf_class": "A", "full_name": "International Conference on Software Engineering", "type": "conference"},
    "ISSTA": {"ccf_class": "A", "full_name": "International Symposium on Software Testing and Analysis", "type": "conference"},
    "OSDI": {"ccf_class": "A", "full_name": "USENIX Symposium on Operating Systems Design and Implementation", "type": "conference"},
    "FM": {"ccf_class": "A", "full_name": "International Symposium on Formal Methods", "type": "conference"},
    "ECOOP": {"ccf_class": "B", "full_name": "European Conference on Object-Oriented Programming", "type": "conference"},
    "ETAPS": {"ccf_class": "B", "full_name": "European Joint Conferences on Theory and Practice of Software", "type": "conference"},
    "ICPC": {"ccf_class": "B", "full_name": "IEEE International Conference on Program Comprehension", "type": "conference"},
    "RE": {"ccf_class": "B", "full_name": "IEEE International Requirements Engineering Conference", "type": "conference"},
    "CAiSE": {"ccf_class": "B", "full_name": "International Conference on Advanced Information Systems Engineering", "type": "conference"},
    "ICFP": {"ccf_class": "B", "full_name": "ACM SIGPLAN International Conference on Function Programming", "type": "conference"},
    "LCTES": {"ccf_class": "B", "full_name": "ACM SIGPLAN/SIGBED International Conference on Languages, Compilers andTools for Embedded Systems", "type": "conference"},
    "MoDELS": {"ccf_class": "B", "full_name": "ACM/IEEE International Conference on Model Driven Engineering Languages and Systems", "type": "conference"},
    "CP": {"ccf_class": "B", "full_name": "International Conference on Principles and Practice of Constraint Programming", "type": "conference"},
    "ICSOC": {"ccf_class": "B", "full_name": "International Conference on Service Oriented Computing", "type": "conference"},
    "SANER": {"ccf_class": "B", "full_name": "IEEE International Conference on Software Analysis, Evolution,and Reengineering", "type": "conference"},
    "ICSME": {"ccf_class": "B", "full_name": "International Conference on Software Maintenance and Evolution", "type": "conference"},
    "VMCAI": {"ccf_class": "B", "full_name": "International Conference on Verification,Model Checking, and Abstract Interpretation", "type": "conference"},
    "ICWS": {"ccf_class": "B", "full_name": "IEEE International Conference on Web Services", "type": "conference"},
    "Middleware": {"ccf_class": "B", "full_name": "International Middleware Conference", "type": "conference"},
    "SAS": {"ccf_class": "B", "full_name": "International Static Analysis Symposium", "type": "conference"},
    "ESEM": {"ccf_class": "B", "full_name": "International Symposium on Empirical Software Engineering and Measurement", "type": "conference"},
    "ISSRE": {"ccf_class": "B", "full_name": "IEEE International Symposium on Software Reliability Engineering", "type": "conference"},
    "HotOS": {"ccf_class": "B", "full_name": "USENIX Workshop on Hot Topics in Operating Systems", "type": "conference"},
    "CC": {"ccf_class": "B", "full_name": "International Conference on Compiler Construction", "type": "conference"},
    "PEPM": {"ccf_class": "C", "full_name": "ACM SIGPLAN Workshop on Partial Evaluation and Program Manipulation", "type": "conference"},
    "PASTE": {"ccf_class": "C", "full_name": "ACMSIGPLAN-SIGSOFT Workshop on Program Analysis for Software Tools and Engineering", "type": "conference"},
    "APLAS": {"ccf_class": "C", "full_name": "Asian Symposium on Programming Languages and Systems", "type": "conference"},
    "APSEC": {"ccf_class": "C", "full_name": "Asia-Pacific Software Engineering Conference", "type": "conference"},
    "EASE": {"ccf_class": "C", "full_name": "International Conference on Evaluation and Assessment in Software Engineering", "type": "conference"},
    "ICECCS": {"ccf_class": "C", "full_name": "International Conference on Engineering of Complex Computer Systems", "type": "conference"},
    "ICST": {"ccf_class": "C", "full_name": "IEEE International Conference on Software Testing, Verification and Validation", "type": "conference"},
    "ISPASS": {"ccf_class": "C", "full_name": "IEEE International Symposium on Performance Analysis of Systems and Software", "type": "conference"},
    "SCAM": {"ccf_class": "C", "full_name": "IEEE International Working Conference on Source Code Analysis and Manipulation", "type": "conference"},
    "COMPSAC": {"ccf_class": "C", "full_name": "International Computer Software and Applications Conference", "type": "conference"},
    "ICFEM": {"ccf_class": "C", "full_name": "International Conference on Formal Engineering Methods", "type": "conference"},
    "SSE": {"ccf_class": "C", "full_name": "IEEE International Conference on Software Services Engineering", "type": "conference"},
    "ICSSP": {"ccf_class": "C", "full_name": "International Conference on Software and System Process", "type": "conference"},
    "SEKE": {"ccf_class": "C", "full_name": "International Conference on Software Engineering and Knowledge Engineering", "type": "conference"},
    "QRS": {"ccf_class": "C", "full_name": "International Conference on Software Quality, Reliability and Security", "type": "conference"},
    "ICSR": {"ccf_class": "C", "full_name": "International Conference on Software Reuse", "type": "conference"},
    "ICWE": {"ccf_class": "C", "full_name": "International Conference on Web Engineering", "type": "conference"},
    "SPIN": {"ccf_class": "C", "full_name": "International Symposium on Model Checking of Software", "type": "conference"},
    "ATVA": {"ccf_class": "C", "full_name": "International Symposium on Automated Technology for Verification and Analysis", "type": "conference"},
    "LOPSTR": {"ccf_class": "C", "full_name": "International Symposium on Logic-based Program Synthesis and Transformation", "type": "conference"},
    "TASE": {"ccf_class": "C", "full_name": "Theoretical Aspects of Software Engineering Conference", "type": "conference"},
    "MSR": {"ccf_class": "C", "full_name": "Mining Software Repositories", "type": "conference"},
    "REFSQ": {"ccf_class": "C", "full_name": "Requirements Engineering: Foundation for Software Quality", "type": "conference"},
    "WICSA": {"ccf_class": "C", "full_name": "Working IEEE/IFIP Conference on Software Architecture", "type": "conference"},
    "Internetware": {"ccf_class": "C", "full_name": "Asia-Pacific Symposium on Internetware", "type": "conference"},
    "RV": {"ccf_class": "C", "full_name": "International Conference on Runtime Verification", "type": "conference"},
    "MEMOCODE": {"ccf_class": "C", "full_name": "International Conference on Formal Methods and Models for Co-Design", "type": "conference"},
    "SIGMOD": {"ccf_class": "A", "full_name": "ACM SIGMOD Conference", "type": "conference"},
    "SIGKDD": {"ccf_class": "A", "full_name": "ACM SIGKDD Conference on Knowledge Discovery and Data Mining", "type": "conference"},
    "ICDE": {"ccf_class": "A", "full_name": "IEEE International Conference on Data Engineering", "type": "conference"},
    "SIGIR": {"ccf_class": "A", "full_name": "International ACM SIGIR Conference on Research and Development in Information Retrieval", "type": "conference"},
    "VLDB": {"ccf_class": "A", "full_name": "International Conference on Very Large Data Bases", "type": "conference"},
    "CIKM": {"ccf_class": "B", "full_name": "ACM International Conference on Information and Knowledge Management", "type": "conference"},
    "WSDM": {"ccf_class": "B", "full_name": "ACM International Conference on Web Search and Data Mining", "type": "conference"},
    "PODS": {"ccf_class": "B", "full_name": "ACM SIGMOD-SIGACT-SIGAI Symposium on Principles of Database Systems", "type": "conference"},
    "DASFAA": {"ccf_class": "B", "full_name": "International Conference on Database Systems for Advanced Applications", "type": "conference"},
    "ECML-PKDD": {"ccf_class": "B", "full_name": "European Conference on Machine Learning and Principles and Practice of Knowledge Discovery in Databases", "type": "conference"},
    "ISWC": {"ccf_class": "B", "full_name": "IEEE International Semantic Web Conference", "type": "conference"},
    "ICDM": {"ccf_class": "B", "full_name": "IEEE International Conference on Data Mining", "type": "conference"},
    "ICDT": {"ccf_class": "B", "full_name": "International Conference on Database Theory", "type": "conference"},
    "EDBT": {"ccf_class": "B", "full_name": "International Conference on Extending DatabaseTechnology", "type": "conference"},
    "CIDR": {"ccf_class": "B", "full_name": "Conference on Innovative DataSystems Research", "type": "conference"},
    "SDM": {"ccf_class": "B", "full_name": "SIAM International Conference on Data Mining", "type": "conference"},
    "RecSys": {"ccf_class": "B", "full_name": "ACM Conference on Recommender Systems", "type": "conference"},
    "WISE": {"ccf_class": "B", "full_name": "Web Information Systems Engineering Conference", "type": "conference"},
    "APWeb": {"ccf_class": "C", "full_name": "Asia Pacific Web Conference", "type": "conference"},
    "DEXA": {"ccf_class": "C", "full_name": "International Conference on Database and Expert System Applications", "type": "conference"},
    "ECIR": {"ccf_class": "C", "full_name": "European Conference on Information Retrieval", "type": "conference"},
    "ESWC": {"ccf_class": "C", "full_name": "Extended Semantic Web Conference", "type": "conference"},
    "WebDB": {"ccf_class": "C", "full_name": "International Workshop on Web andDatabases", "type": "conference"},
    "ER": {"ccf_class": "C", "full_name": "International Conference on Conceptual Modeling", "type": "conference"},
    "MDM": {"ccf_class": "C", "full_name": "International Conference on Mobile Data Management", "type": "conference"},
    "SSDBM": {"ccf_class": "C", "full_name": "International Conference on Scientific andStatistical Database Management", "type": "conference"},
    "WAIM": {"ccf_class": "C", "full_name": "International Conference on Web Age Information Management", "type": "conference"},
    "SSTD": {"ccf_class": "C", "full_name": "International Symposium on Spatial and Temporal Databases", "type": "conference"},
    "PAKDD": {"ccf_class": "C", "full_name": "Pacific-Asia Conference on Knowledge Discovery and Data Mining", "type": "conference"},
    "ADMA": {"ccf_class": "C", "full_name": "International Conference on Advanced Data Mining and Applications", "type": "conference"},
    "WISA": {"ccf_class": "C", "full_name": "Web Information Systems and Applications", "type": "conference"},
    "STOC": {"ccf_class": "A", "full_name": "ACM Symposium on the Theory of Computing", "type": "conference"},
    "SODA": {"ccf_class": "A", "full_name": "ACM-SIAM Symposium on Discrete Algorithms", "type": "conference"},
    "CAV": {"ccf_class": "A", "full_name": "International Conference on Computer Aided Verification", "type": "conference"},
    "FOCS": {"ccf_class": "A", "full_name": "IEEE Annual Symposium on Foundations of Computer Science", "type": "conference"},
    "LICS": {"ccf_class": "A", "full_name": "ACM/IEEE Symposium on Logic in Computer Science", "type": "conference"},
    "SoCG": {"ccf_class": "B", "full_name": "International Symposium on Computational Geometry", "type": "conference"},
    "ESA": {"ccf_class": "B", "full_name": "European Symposium on Algorithms", "type": "conference"},
    "CCC": {"ccf_class": "B", "full_name": "Conference on Computational Complexity", "type": "conference"},
    "ICALP": {"ccf_class": "B", "full_name": "International Colloquium on Automata, Languages and Programming", "type": "conference"},
    "CADE": {"ccf_class": "B", "full_name": "Conference on Automated Deduction", "type": "conference"},
    "CONCUR": {"ccf_class": "B", "full_name": "International Conference on Concurrency Theory", "type": "conference"},
    "HSCC": {"ccf_class": "B", "full_name": "International Conference on Hybrid Systems: Computation and Control", "type": "conference"},
    "SAT": {"ccf_class": "B", "full_name": "International Conference on Theory and Applications of Satisfiability Testing", "type": "conference"},
    "COCOON": {"ccf_class": "B", "full_name": "International Computing and Combinatorics Conference", "type": "conference"},
    "FMCAD": {"ccf_class": "B", "full_name": "Formal Methods in Computer-Aided Design", "type": "conference"},
    "CSL": {"ccf_class": "C", "full_name": "Computer Science Logic", "type": "conference"},
    "FSTTCS": {"ccf_class": "C", "full_name": "Foundations of Software Technology and Theoretical Computer Science", "type": "conference"},
    "DSAA": {"ccf_class": "C", "full_name": "IEEE International Conference on Data Science and Advanced Analytics", "type": "conference"},
    "ICTAC": {"ccf_class": "C", "full_name": "International Colloquium on Theoretical Aspects of Computing", "type": "conference"},
    "IPCO": {"ccf_class": "C", "full_name": "International Conference on Integer Programming and Combinatorial Optimization", "type": "conference"},
    "FSCD": {"ccf_class": "C", "full_name": "International Conference on Formal Structures for Computation and Deduction", "type": "conference"},
    "ISAAC": {"ccf_class": "C", "full_name": "International Symposium on Algorithms and Computation", "type": "conference"},
    "MFCS": {"ccf_class": "C", "full_name": "International Conference on Mathematical Foundations of Computer Science", "type": "conference"},
    "STACS": {"ccf_class": "C", "full_name": "Symposium on Theoretical Aspects of Computer Science", "type": "conference"},
    "SETTA": {"ccf_class": "C", "full_name": "International Symposium on Software Engineering: Theories, Tools, and Applications", "type": "conference"},
    "ACM MM": {"ccf_class": "A", "full_name": "ACM International Conference on Multimedia", "type": "conference"},
    "SIGGRAPH": {"ccf_class": "A", "full_name": "ACM Special Interest Group on Computer Graphics", "type": "conference"},
    "VR": {"ccf_class": "A", "full_name": "IEEE Conference on Virtual Reality and 3D User Interfaces", "type": "conference"},
    "IEEE VIS": {"ccf_class": "A", "full_name": "IEEE Visualization Conference", "type": "conference"},
    "ICMR": {"ccf_class": "B", "full_name": "ACM SIGMM International Conference on Multimedia Retrieval", "type": "conference"},
    "I3D": {"ccf_class": "B", "full_name": "ACM SIGGRAPH Symposium onInteractive 3D Graphics and Games", "type": "conference"},
    "SCA": {"ccf_class": "B", "full_name": "ACM SIGGRAPH/Eurographics Symposium on Computer Animation", "type": "conference"},
    "DCC": {"ccf_class": "B", "full_name": "Data Compression Conference", "type": "conference"},
    "Eurographics": {"ccf_class": "B", "full_name": "Annual Conference of the European Association for Computer Graphics", "type": "conference"},
    "EuroVis": {"ccf_class": "B", "full_name": "Eurographics Conference on Visualization", "type": "conference"},
    "SGP": {"ccf_class": "B", "full_name": "Eurographics Symposium on Geometry Processing", "type": "conference"},
    "EGSR": {"ccf_class": "B", "full_name": "Eurographics Symposium on Rendering", "type": "conference"},
    "ICASSP": {"ccf_class": "B", "full_name": "IEEE International Conference on Acoustics,Speech and Signal Processing", "type": "conference"},
    "ICME": {"ccf_class": "B", "full_name": "IEEE International Conference on Multimedia& Expo", "type": "conference"},
    "ISMAR": {"ccf_class": "B", "full_name": "International Symposium on Mixed and Augmented Reality", "type": "conference"},
    "PG": {"ccf_class": "B", "full_name": "Pacific Conference on Computer Graphics and Applications", "type": "conference"},
    "SPM": {"ccf_class": "B", "full_name": "Symposium on Solid and Physical Modeling", "type": "conference"},
    "INTERSPEECH": {"ccf_class": "B", "full_name": "Conference of the International Speech Communication Association", "type": "conference"},
    "VRST": {"ccf_class": "C", "full_name": "ACM Symposium on Virtual Reality Software and Technology", "type": "conference"},
    "CASAXR": {"ccf_class": "C", "full_name": "International Conference on Computer Animation, Social Agents, and Extended Reality", "type": "conference"},
    "CGI": {"ccf_class": "C", "full_name": "Computer Graphics International", "type": "conference"},
    "GMP": {"ccf_class": "C", "full_name": "Geometric Modeling and Processing", "type": "conference"},
    "PacificVis": {"ccf_class": "C", "full_name": "IEEE Pacific Visualization Symposium", "type": "conference"},
    "3DV": {"ccf_class": "C", "full_name": "International Conference on 3D Vision", "type": "conference"},
    "CAD/Graphics": {"ccf_class": "C", "full_name": "International Conference on Computer-Aided Design and Computer Graphics", "type": "conference"},
    "ICIP": {"ccf_class": "C", "full_name": "IEEE International Conference on Image Processing", "type": "conference"},
    "MMM": {"ccf_class": "C", "full_name": "International Conference on Multimedia Modeling", "type": "conference"},
    "MMAsia": {"ccf_class": "C", "full_name": "ACM Multimedia Asia", "type": "conference"},
    "SMI": {"ccf_class": "C", "full_name": "Shape Modeling International", "type": "conference"},
    "CVM": {"ccf_class": "C", "full_name": "Computational Visual Media", "type": "conference"},
    "PRCV": {"ccf_class": "C", "full_name": "Chinese Conference on Pattern Recognition and Computer Vision", "type": "conference"},
    "ICIG": {"ccf_class": "C", "full_name": "International Conference on Image and Graphics", "type": "conference"},
    "NCMMSC": {"ccf_class": "C", "full_name": "National Conference on Man-Machine Speech Communication", "type": "conference"},
    "ASRU": {"ccf_class": "C", "full_name": "Automatic Speech Recognition and Understanding Workshop", "type": "conference"},
    "SLT": {"ccf_class": "C", "full_name": "Spoken Language Technology", "type": "conference"},
    "AAAI": {"ccf_class": "A", "full_name": "AAAI Conference on Artificial Intelligence", "type": "conference"},
    "NeurIPS": {"ccf_class": "A", "full_name": "Conference on Neural Information Processing Systems", "type": "conference"},
    "ACL": {"ccf_class": "A", "full_name": "Annual Meeting of the Association for Computational Linguistics", "type": "conference"},
    "CVPR": {"ccf_class": "A", "full_name": "IEEE/CVF Computer Vision and Pattern Recognition Conference", "type": "conference"},
    "ICCV": {"ccf_class": "A", "full_name": "International Conference on Computer Vision", "type": "conference"},
    "ICML": {"ccf_class": "A", "full_name": "International Conference on Machine Learning", "type": "conference"},
    "ICLR": {"ccf_class": "A", "full_name": "International Conference on Learning Representations", "type": "conference"},
    "COLT": {"ccf_class": "B", "full_name": "Annual Conference on Computational Learning Theory", "type": "conference"},
    "EMNLP": {"ccf_class": "B", "full_name": "Conference on Empirical Methods in Natural Language Processing", "type": "conference"},
    "ECAI": {"ccf_class": "B", "full_name": "European Conference on Artificial Intelligence", "type": "conference"},
    "ECCV": {"ccf_class": "B", "full_name": "European Conference on Computer Vision", "type": "conference"},
    "ICRA": {"ccf_class": "B", "full_name": "IEEE International Conference on Robotics and Automation", "type": "conference"},
    "ICAPS": {"ccf_class": "B", "full_name": "International Conference on Automated Planning and Scheduling", "type": "conference"},
    "ICCBR": {"ccf_class": "B", "full_name": "International Conference on Case-Based Reasoning", "type": "conference"},
    "COLING": {"ccf_class": "B", "full_name": "International Conference on Computational Linguistics", "type": "conference"},
    "KR": {"ccf_class": "B", "full_name": "International Conference on Principles of Knowledge Representation and Reasoning", "type": "conference"},
    "UAI": {"ccf_class": "B", "full_name": "Conference on Uncertainty in ArtificialIntelligence", "type": "conference"},
    "AAMAS": {"ccf_class": "B", "full_name": "International Joint Conference on Autonomous Agents and Multi-agent Systems", "type": "conference"},
    "PPSN": {"ccf_class": "B", "full_name": "Parallel Problem Solving from Nature", "type": "conference"},
    "NAACL": {"ccf_class": "B", "full_name": "North American Chapter of the Associationfor Computational Linguistics", "type": "conference"},
    "IJCAI": {"ccf_class": "B", "full_name": "International Joint Conference on Artificial Intelligence", "type": "conference"},
    "AISTATS": {"ccf_class": "C", "full_name": "International Conference on Artificial Intelligence and Statistics", "type": "conference"},
    "ACCV": {"ccf_class": "C", "full_name": "Asian Conference on Computer Vision", "type": "conference"},
    "ACML": {"ccf_class": "C", "full_name": "Asian Conference on Machine Learning", "type": "conference"},
    "BMVC": {"ccf_class": "C", "full_name": "British Machine Vision Conference", "type": "conference"},
    "NLPCC": {"ccf_class": "C", "full_name": "CCF International Conference on Natural Language Processing and Chinese Computing", "type": "conference"},
    "CoNLL": {"ccf_class": "C", "full_name": "Conference on Computational Natural Language Learning", "type": "conference"},
    "GECCO": {"ccf_class": "C", "full_name": "Genetic and Evolutionary Computation Conference", "type": "conference"},
    "ICTAI": {"ccf_class": "C", "full_name": "IEEE International Conference on Tools with Artificial Intelligence", "type": "conference"},
    "IROS": {"ccf_class": "C", "full_name": "IEEE/RSJ International Conference on Intelligent Robots and Systems", "type": "conference"},
    "ALT": {"ccf_class": "C", "full_name": "International Conference on Algorithmic Learning Theory", "type": "conference"},
    "ICANN": {"ccf_class": "C", "full_name": "International Conference on Artificial Neural Networks", "type": "conference"},
    "FG": {"ccf_class": "C", "full_name": "IEEE International Conference on AutomaticFace and Gesture Recognition", "type": "conference"},
    "ICDAR": {"ccf_class": "C", "full_name": "International Conference on Document Analysis and Recognition", "type": "conference"},
    "ILP": {"ccf_class": "C", "full_name": "International Conference on Inductive Logic Programming", "type": "conference"},
    "KSEM": {"ccf_class": "C", "full_name": "International conference on Knowledge Science,Engineering and Management", "type": "conference"},
    "ICONIP": {"ccf_class": "C", "full_name": "International Conference on Neural Information Processing", "type": "conference"},
    "ICPR": {"ccf_class": "C", "full_name": "International Conference on Pattern Recognition", "type": "conference"},
    "IJCB": {"ccf_class": "C", "full_name": "International Joint Conference onBiometrics", "type": "conference"},
    "IJCNN": {"ccf_class": "C", "full_name": "International Joint Conference on Neural Networks", "type": "conference"},
    "PRICAI": {"ccf_class": "C", "full_name": "Pacific Rim International Conference on Artificial Intelligence", "type": "conference"},
    "IEEE CEC": {"ccf_class": "C", "full_name": "Congress on Evolutionary Computation", "type": "conference"},
    "DAI": {"ccf_class": "C", "full_name": "International Conference on Distributed Artificial Intelligence", "type": "conference"},
    "CSCW": {"ccf_class": "A", "full_name": "ACM Conference on Computer Supported Cooperative Work and Social Computing", "type": "conference"},
    "CHI": {"ccf_class": "A", "full_name": "ACM Conference on Human Factors in Computing Systems", "type": "conference"},
    "UbiComp": {"ccf_class": "A", "full_name": "ACM International Joint Conference on Pervasive and Ubiquitous Computing", "type": "conference"},
    "UIST": {"ccf_class": "A", "full_name": "ACM Symposium on User Interface Software and Technology", "type": "conference"},
    "GROUP": {"ccf_class": "B", "full_name": "ACM International Conference on Supporting Group Work", "type": "conference"},
    "IUI": {"ccf_class": "B", "full_name": "ACM International Conference on Intelligent User Interfaces", "type": "conference"},
    "ISS": {"ccf_class": "B", "full_name": "ACM International Conference on Interactive Surfaces and Spaces", "type": "conference"},
    "ECSCW": {"ccf_class": "B", "full_name": "European Conference on Computer Supported Cooperative Work", "type": "conference"},
    "PERCOM": {"ccf_class": "B", "full_name": "IEEE International Conference on Pervasive Computing and Communications", "type": "conference"},
    "MobileHCI": {"ccf_class": "B", "full_name": "ACM International Conference on Mobile Human-Computer Interaction", "type": "conference"},
    "ICWSM": {"ccf_class": "B", "full_name": "The International AAAI Conference on Web and Social Media", "type": "conference"},
    "DIS": {"ccf_class": "C", "full_name": "ACM SIGCHI Conference on Designing Interactive Systems", "type": "conference"},
    "ICMI": {"ccf_class": "C", "full_name": "ACM International Conference on Multimodal Interaction", "type": "conference"},
    "ASSETS": {"ccf_class": "C", "full_name": "International ACM SIGACCESS Conference on Computers and Accessibility", "type": "conference"},
    "GI": {"ccf_class": "C", "full_name": "Graphics Interface", "type": "conference"},
    "UIC": {"ccf_class": "C", "full_name": "IEEE International Conference on Ubiquitous Intelligence and Computing", "type": "conference"},
    "INTERACT": {"ccf_class": "C", "full_name": "International Conference on Human- Computer Interaction of International Federation for Information Processing", "type": "conference"},
    "IDC": {"ccf_class": "C", "full_name": "ACM Interaction Design and Children", "type": "conference"},
    "CollaborateCom": {"ccf_class": "C", "full_name": "International Conference on Collaborative Computing:Networking, Applications and Worksharing", "type": "conference"},
    "CSCWD": {"ccf_class": "C", "full_name": "International Conference on Computer Supported Cooperative Work in Design", "type": "conference"},
    "CoopIS": {"ccf_class": "C", "full_name": "International Conference on Cooperative Information Systems", "type": "conference"},
    "MobiQuitous": {"ccf_class": "C", "full_name": "International Conference on Mobile and Ubiquitous Systems: Computing,Networking and Services", "type": "conference"},
    "AVI": {"ccf_class": "C", "full_name": "International Working Conference on Advanced Visual Interfaces", "type": "conference"},
    "GPC": {"ccf_class": "C", "full_name": "Conference on Green, Pervasive and Cloud Computing", "type": "conference"},
    "ICXR": {"ccf_class": "C", "full_name": "CCF International Conference on Extended Reality", "type": "conference"},
    "WWW": {"ccf_class": "A", "full_name": "The Web Conference", "type": "conference"},
    "RTSS": {"ccf_class": "A", "full_name": "IEEE Real-Time Systems Symposium", "type": "conference"},
    "CogSci": {"ccf_class": "B", "full_name": "Annual Meeting of the Cognitive Science Society", "type": "conference"},
    "BIBM": {"ccf_class": "B", "full_name": "IEEE International Conference on Bioinformatics and Biomedicine", "type": "conference"},
    "EMSOFT": {"ccf_class": "B", "full_name": "International Conference on Embedded Software", "type": "conference"},
    "ISMB": {"ccf_class": "B", "full_name": "International conference on Intelligent Systems for Molecular Biology", "type": "conference"},
    "RECOMB": {"ccf_class": "B", "full_name": "Annual International Conference on Research inComputational Molecular Biology", "type": "conference"},
    "MICCAI": {"ccf_class": "B", "full_name": "International Conference on Medical Image Computing and Computer-Assisted Intervention", "type": "conference"},
    "WINE": {"ccf_class": "B", "full_name": "Conference on Web and Internet Economics", "type": "conference"},
    "AMIA": {"ccf_class": "C", "full_name": "American Medical Informatics Association Annual Symposium", "type": "conference"},
    "APBC": {"ccf_class": "C", "full_name": "Asia Pacific Bioinformatics Conference", "type": "conference"},
    "IEEE BigData": {"ccf_class": "C", "full_name": "IEEE International Conference on Big Data", "type": "conference"},
    "IEEE CLOUD": {"ccf_class": "C", "full_name": "IEEE International Conference on Cloud Computing", "type": "conference"},
    "SMC": {"ccf_class": "C", "full_name": "IEEE International Conference on Systems, Man, and Cybernetics", "type": "conference"},
    "COSIT": {"ccf_class": "C", "full_name": "International Conference on Spatial Information Theory", "type": "conference"},
    "ISBRA": {"ccf_class": "C", "full_name": "International Symposium on Bioinformatics Research and Applications", "type": "conference"},
    "SAGT": {"ccf_class": "C", "full_name": "International Symposium on Algorithmic Game Theory", "type": "conference"},
    "SIGSPATIAL": {"ccf_class": "C", "full_name": "ACM Special Interest Group on Spatial Information", "type": "conference"},
    "ICIC": {"ccf_class": "C", "full_name": "International Conference on Intelligent Computing", "type": "conference"},
    "ICSS": {"ccf_class": "C", "full_name": "International Conference on Service Science", "type": "conference"},
    "AFT": {"ccf_class": "C", "full_name": "Advances in Financial Technologies", "type": "conference"},
    "IJTCS-FAW": {"ccf_class": "C", "full_name": "International Joint Conference on Theoretical Computer Science-Frontier of Algorithmic Wisdom", "type": "conference"},
}

VENUE_ALIASES = {
    # CVPR别名
    "IEEE Conference on Computer Vision and Pattern Recognition": "CVPR",
    "Computer Vision and Pattern Recognition": "CVPR",
    "IEEE/CVF CVPR": "CVPR",

    # ICCV别名
    "International Conference on Computer Vision": "ICCV",
    "IEEE ICCV": "ICCV",

    # SIGMOD别名
    "ACM SIGMOD Conference": "SIGMOD",
    "ACM SIGMOD International Conference on Management of Data": "SIGMOD",
    "SIGMOD Conference": "SIGMOD",

    # ICSE别名
    "International Conference on Software Engineering": "ICSE",
    "ICSE Conference": "ICSE",

    # AAAI别名
    "AAAI Conference on Artificial Intelligence": "AAAI",
    "National Conference on Artificial Intelligence": "AAAI",  # 历史名称

    # IJCAI别名
    "International Joint Conference on Artificial Intelligence": "IJCAI",
    "IJCAI Conference": "IJCAI",

    # NeurIPS别名
    "Neural Information Processing Systems": "NeurIPS",
    "NIPS": "NeurIPS",  # 历史缩写
    "Advances in Neural Information Processing Systems": "NeurIPS",

    # WWW别名
    "The Web Conference": "WWW",
    "World Wide Web Conference": "WWW",
    "International World Wide Web Conferences": "WWW",

    # CIKM别名
    "ACM International Conference on Information and Knowledge Management": "CIKM",
    "ACM CIKM": "CIKM",

    # CHI别名
    "ACM CHI": "CHI",
    "Conference on Human Factors in Computing Systems": "CHI",
    "ACM Conference on Human Factors in Computing Systems": "CHI",

    # 期刊别名
    "IEEE Transactions on Software Engineering": "IEEE TSE",
    "ACM Transactions on Software Engineering and Methodology": "ACM TOSEM",
    "IEEE Transactions on Pattern Analysis and Machine Intelligence": "IEEE TPAMI",
    "Journal of the ACM": "JACM",
    "ACM Transactions on Graphics": "ACM TOG",
}


def get_ccf_classification(venue_name: str) -> dict:
    """
    根据venue名称获取CCF分类信息

    Args:
        venue_name: venue名称（可以是缩写或全称）

    Returns:
        包含ccf_class和type的字典，如果未找到则返回None
    """
    if not venue_name:
        return None

    # 使用统一的CCF映射表
    ALL_CCF_VENUES = CCF_VENUES

    # 阶段1：检查别名映射（最高优先级）
    if venue_name in VENUE_ALIASES:
        alias_target = VENUE_ALIASES[venue_name]
        if alias_target in ALL_CCF_VENUES:
            return ALL_CCF_VENUES[alias_target]

    # 阶段2：精确匹配
    if venue_name in ALL_CCF_VENUES:
        return ALL_CCF_VENUES[venue_name]

    # 阶段3：去除年份和额外信息进行匹配
    # 例如：CVPR 2024 → CVPR
    import re
    cleaned_name = re.sub(r'\s*\d{4}\s*$', '', venue_name.strip())

    # 对清理后的名称也检查别名
    if cleaned_name in VENUE_ALIASES:
        alias_target = VENUE_ALIASES[cleaned_name]
        if alias_target in ALL_CCF_VENUES:
            return ALL_CCF_VENUES[alias_target]

    if cleaned_name in ALL_CCF_VENUES:
        return ALL_CCF_VENUES[cleaned_name]

    # 阶段4：关键词匹配 - 提取全大写的缩写词
    words = venue_name.split()
    for word in words:
        # 查找全大写的缩写词（至少2个字符）
        if word.isupper() and len(word) >= 2 and word in ALL_CCF_VENUES:
            return ALL_CCF_VENUES[word]

    # 阶段5：优化的全称匹配
    # 使用更智能的匹配策略
    for ccf_name, ccf_info in ALL_CCF_VENUES.items():
        if len(ccf_name) >= 3:  # 只考虑长度>=3的CCF名称
            ccf_name_lower = ccf_name.lower()
            venue_name_lower = venue_name.lower()

            # 检查是否包含CCF名称
            if ccf_name_lower in venue_name_lower:
                # 计算匹配质量
                match_ratio = len(ccf_name) / len(venue_name)

                # 避免匹配太通用的词
                common_words = {'conference', 'symposium', 'workshop', 'journal',
                               'transactions', 'international', 'acm', 'ieee',
                               'computer', 'science', 'engineering', 'proceedings'}

                if ccf_name_lower not in common_words and match_ratio > 0.25:
                    return ccf_info

    # 阶段6：尝试从全称中提取缩写
    # 例如："International Conference on Computer Vision" → "ICCV"
    extracted_acronym = extract_acronym(venue_name)
    if extracted_acronym and extracted_acronym in ALL_CCF_VENUES:
        return ALL_CCF_VENUES[extracted_acronym]

    return None


def extract_acronym(text: str) -> str:
    """
    从全称中提取缩写
    例如："International Conference on Computer Vision" → "ICCV"

    Args:
        text: venue全称

    Returns:
        提取的缩写，如果无法提取则返回None
    """
    # 移除常见的停用词
    stop_words = {'on', 'of', 'the', 'and', 'in', 'for', 'with', 'at', 'from', 'to'}
    words = text.split()

    # 提取每个单词的首字母（跳过停用词）
    acronym_letters = []
    for word in words:
        clean_word = word.strip('(),.:;-')
        if clean_word and clean_word.lower() not in stop_words:
            if clean_word[0].isupper():
                acronym_letters.append(clean_word[0])

    # 如果提取的字母太多（超过6个），可能不是正确的缩写
    if 2 <= len(acronym_letters) <= 6:
        acronym = ''.join(acronym_letters)
        return acronym

    return None

    return None


def get_ccf_class(venue_name: str) -> str:
    """
    获取venue的CCF等级

    Args:
        venue_name: venue名称

    Returns:
        CCF等级（'A', 'B', 'C'）或None
    """
    ccf_info = get_ccf_classification(venue_name)
    if ccf_info:
        return ccf_info["ccf_class"]
    return None


if __name__ == "__main__":
    # 测试代码
    test_venues = [
        # A类会议
        "CVPR", "SIGMOD", "ICSE 2024",
        # B类会议
        "ICCV", "CIKM", "ECOOP", "SoCC", "EMNLP",
        # 未匹配
        "Unknown Conference"
    ]
    for venue in test_venues:
        ccf_info = get_ccf_classification(venue)
        if ccf_info:
            print(f"{venue}: CCF {ccf_info['ccf_class']} - {ccf_info['full_name']}")
        else:
            print(f"{venue}: Not found in CCF list")