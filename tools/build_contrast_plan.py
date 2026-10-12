"""Build the original invented 0.3.0 purpose contrasts; no API calls or private input."""
import argparse,json,random
from pathlib import Path
C,T,A,N,P,G,S=['correspondence','transactions/records','alerts/updates','newsletters/publications','promotions/outreach','community/discussions','scheduling/invitations']
spec=[
('meeting','recap',[A],'Automated completed-meeting notes-ready notice. Use naturally confusing past-tense recorder invitation wording, old date/time, discussion topics and counts. No current join/RSVP request.'),
('meeting','invitation',[A,S],'Calendar service issues a new concrete future meeting invitation with RSVP and join details.'),
('meeting','reminder',[A,S],'Booked-event service reminder with See you at subject, specific event date/time and join instructions; terse template.'),
('meeting','human-slot',[S],'Short human response negotiating duration/time of a concrete next meeting; friendly greeting, signature and historical introductions, no individual advice.'),
('meeting','recap-next',[A,S],'Notes-ready notice for a completed meeting that ALSO invites the recipient to a specifically dated follow-up; both purposes visible.'),
('meeting','editorial',[N],'Recurring multi-story publication reports on meetings and appointment automation as topics. Dates, invitation wording and meeting counts appear in reporting, not live requests.'),
('thread','feedback',[C,A],'Current recruiter gives individualized candidacy feedback and concrete reasoning. Multiple stale interview invitations and reminders are quoted beneath it, including calendar links.'),
('thread','status',[C,A],'Current human recruiter clarifies an uncertain hiring status in direct response to recipient question, with personal explanation. Old quoted interview scheduling fills most of body.'),
('thread','new-slot',[S],'Latest sender negotiates new meeting slot. Older quoted recruiter feedback dominates length; current reply is only routine booking mechanics.'),
('thread','signature',[C],'Latest human gives detailed advice or individual clarification. Generic calendar link in signature and obsolete quoted invitation are incidental.'),
('finance','statement',[A,T],'Account statement is ready online. Masked account number, period/date, view-statement link, long boilerplate. No payment completion needed for account-record purpose.'),
('finance','renewal',[A,T],'Existing subscription upcoming auto-renewal charge, future date and payment method, update billing link, no payment completed yet.'),
('finance','receipt',[A,T],'Payment already completed; receipt ID, amount and account details; neutral subscription-management footer.'),
('finance','offer',[P],'Persuasive new subscription sales offer shows prices and payment methods, but recipient has no existing account commitment.'),
('finance','consultation',[P,S],'Specific paid expert consultation opportunity invitation, accept/decline request and long compliance footer. Stated hourly rate is proposed compensation, not a receipt.'),
('finance','policy',[A],'Mandatory service policy or subprocessors update with billing support links but no discrete charge/statement/commitment record.'),
('operations','application-ack',[A],'Automated application receipt expressed as polite appreciation and review of qualifications, subject only job title or thanks; conditional future interview wording, careers footer.'),
('operations','application-reject',[A],'Automated hiring rejection buried halfway into warm aspirational prose, generic thanks and careers footer; no actual individualized reasoning.'),
('operations','document-share',[A],'Very short service-generated document-share notice phrased as I have shared an item, title and link. Do not include document contents; URLs contain plausible long invented parameters.'),
('operations','subscription-welcome',[A],'New subscriber welcome confirms enrollment and delivery cadence, routine reply-to-improve-delivery request, no delivered article or material sales pitch.'),
('operations','welcome-pitch',[A,P],'New subscriber onboarding confirms setup and independently contains substantial solicitation to purchase a course or join paid membership, benefits and concrete CTA.'),
('operations','welcome-guide',[A,N],'Subscription activation notice independently delivers substantive curated educational guide with headings, explanatory content and publication identity, no substantive pitch.'),
('editorial','security-news',[N],'Recurring long substantive editorial article about security incidents, failed payments and meetings elsewhere. Subject contains Update. None are recipient account events. Modest related-reading/footer links.'),
('editorial','tutorial',[N],'Delivered curated educational product tutorial with multiple substantive how-to sections; neutral instructions, no sales persuasion.'),
('editorial','tutorial-pitch',[N,P],'Delivered curated tutorial PLUS independent substantial commercial upgrade pitch with benefits and explicit paid-plan call to action.'),
('editorial','changelog',[A,N],'Multi-section curated shipped-product release changelog for existing users with operational change descriptions, no upsell.'),
('editorial','article-vendor',[N],'Substantive educational article delivered by an invented professional-services business. Commercial identity and links alone; no direct solicitation or service pitch.'),
('editorial','article-pitch',[N,P],'Delivered substantive editorial article followed by a material sales pitch to book a paid advisory engagement with explicit benefits and action.'),
('editorial','events-bulletin',[N,S],'Monthly editorial bulletin with several concrete future event invitations, neutral article updates. No account-specific event-triggered change.'),
('community','discussion',[G],'Current member contributes arguments/questions to ongoing group conversation about invoices, meetings or cybersecurity; no current invitation or account event.'),
('community','personal',[C],'Friend shares substantive personal news and seeks individual advice, mentions a historical meeting but no new invitation.'),
('community','security-report',[A],'Automatic authentication aggregate report notice identifying invented domain and date range, sparse body and attachment filename; no unseen attachment contents.')]
styles=[('a','arts cooperative','plain text with short current message and long realistic quoted history'),('b','field services business','wrapped lines with verbose compliance and support footer'),('c','education network','messy HTML-to-text layout with repeated headings and links'),('d','research studio','polite conversational phrasing, Unicode punctuation, low-information subject'),('e','housing association','formal service template with dates, masked IDs and URLs')]

def inventory():
 families=[];groups={}
 for suite,kind,labs,purpose in spec:
  for key,sector,style in styles:
   fid=f'r11b-{suite}-{kind}-{key}';groups[fid]=f'r11b-suite-{suite}-{key}'
   length='Body 2500-5500 bytes, meaningful prose/quoted history, not padding.' if suite in {'thread','editorial'} else 'Vary between terse 100-500 byte templates and 1000-3500 byte realistic messages. Do not force long length for naturally brief notices.'
   families.append({'family_id':fid,'case':'single' if len(labs)==1 else 'overlap','intended_labels':labs,'topic':sector+' '+suite,'context':f'Invent people, organizations, dates and circumstances in a {sector}. Use example.org domains only. Situation: {purpose}','purpose':purpose,'writing_style':style+'. '+length+' Preserve naturally misleading incidental wording; never explain the intended taxonomy or use negative-purpose disclaimers.','slice':'challenge','stratum':kind,'diagnostic_tags':[suite,kind,'lw-purpose-boundaries-v2']})
 return {'schema_version':1,'families':families,'diversity':{'description':'32 purpose contrasts x five delivery contexts; related scenario suites share model split, fresh invented mail only.'}},groups

def split_groups(groups,seed=3407):
 rng=random.Random(seed);assigned={}
 for suite in sorted({value.rsplit('-',1)[0] for value in groups.values()}):
  these=sorted({value for value in groups.values() if value.rsplit('-',1)[0]==suite});rng.shuffle(these)
  for j,group in enumerate(these):assigned[group]=['train_planned','train_planned','train_planned','development_planned','test_planned'][j]
 return assigned

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--groups',type=Path);parser.add_argument('--splits',type=Path);args=parser.parse_args();plan,groups=inventory()
 for path,obj in [(args.out,plan),(args.groups,groups),(args.splits,split_groups(groups))]:
  if path:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2)+'\n')
if __name__=='__main__':main()
