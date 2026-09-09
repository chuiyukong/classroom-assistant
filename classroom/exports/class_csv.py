"""Teacher-only class export through module-owned export interfaces."""
import csv
import json
from io import BytesIO, StringIO
from classroom.core.errors import AppError


class ClassCsvExport:
    def __init__(self,database,classes,seating,attendance,rollcall):
        self.database,self.classes,self.seating,self.attendance,self.rollcall=database,classes,seating,attendance,rollcall

    def export(self,ids):
        if not isinstance(ids,list) or not ids or len(ids)>500 or any(not isinstance(i,str) or len(i)!=32 for i in ids):
            raise AppError('请先选择需要导出的班级')
        ids=list(dict.fromkeys(ids))
        with self.database.connect() as db:
            groups={}
            for service in (self.classes,self.seating,self.seating.students,self.attendance,self.rollcall):
                groups.update(service.export_data(db,ids))
            layouts={r['layout_id'] for r in groups['rounds']}
            groups['layouts']=[];groups['seat_configs']=[]
            for lid in sorted(layouts):
                groups['layouts'].append({'layout_id':lid,'definition':json.dumps(self.seating.layouts.get(lid,db),ensure_ascii=False)})
                groups['seat_configs'].extend(self.seating.seats.read(db,lid).values())
        labels={'classes':'班级','students':'学生资料及备注','rounds':'座位登记及存档','registrations':'座位记录',
                'submissions':'登记收据','lessons':'课堂','attendance_entries':'考勤','attendance_events':'签到设备及纠正记录',
                'attendance_leave':'长期请假','seat_change_requests':'换座申请','rollcall_draws':'旧版点名记录',
                'rollcall_selections':'最后手动点名范围','layouts':'教室布局','seat_configs':'共用设备配置'}
        columns=['class_id','id','lesson_id','student_id','round_id','name','graduation_year','year','semester','seat_no','status']
        for rows in groups.values():
            for row in rows:
                columns.extend(k for k in row if k not in columns)
        stream=StringIO(newline='');writer=csv.writer(stream)
        writer.writerow(['数据类型']+columns)
        def safe(value):
            value='' if value is None else str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for kind,rows in groups.items():
            for row in rows:
                if kind=='classes':row=dict(row,class_id=row['id'])
                writer.writerow([labels[kind]]+[safe(row.get(k)) for k in columns])
        return BytesIO(stream.getvalue().encode('utf-8-sig'))
